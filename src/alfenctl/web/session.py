"""The one connection to the charger, and everything that queues behind it.

The charger binds its login session to the TCP connection and serves only
ONE connection at a time (see :mod:`alfenctl.charger`).  So the server does
not let request handlers talk to it: every call is a task submitted to this
worker, which owns the single :class:`~alfenctl.charger.AlfenCharger` and
runs tasks one at a time on its own thread.

The queue, the job registry, the activity ticker and the published link
state are :class:`devicectl.web.worker.Worker`, which is that machine
without a charger in it.  What is here is what a charger adds: logging in,
reading the nameplate once the session is up, logging out politely on the
way down, and the station a task is aimed at.

Two ways in:

* :meth:`StationWorker.run` for the short reads a page needs, which blocks
  the calling request thread until the worker gets to it;
* :meth:`StationWorker.start_job` for the slow ones (firmware, logo), which
  returns immediately and reports progress as events.

When nothing is going on the worker logs out and drops the connection
(:data:`DEFAULT_IDLE_TIMEOUT_S`), handing the charger back to whatever else
wants it -- a terminal running ``alfenctl``, or the charger's own web page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from devicectl.errors import describe
from devicectl.web.events import Broadcaster
from devicectl.web.http import HTTP_CONFLICT
from devicectl.web.worker import (
    ACTIVITY_HISTORY,
    DEFAULT_IDLE_TIMEOUT_S,
    DEFAULT_POLL_INTERVAL_S,
    JOB_NOTIFY_INTERVAL_S,
    JOB_RETENTION_S,
    LOOP_TICK_S,
    MAX_POLL_INTERVAL_S,
    MIN_POLL_INTERVAL_S,
    STOP_JOIN_S,
    Job,
    Worker,
)

from alfenctl.charger import AlfenCharger, ChargerInfo
from alfenctl.discovery import Station
from alfenctl.errors import AlfenError
from alfenctl.firmware import device_family

# Link states, as published to the UI.  The shared worker names them and this
# program keeps its names: the page's stylesheet and JavaScript are written
# against these strings, so they are spelled once, here, rather than as
# literals on both sides of the wire.
LINK_RELEASED = Worker.RELEASED  # no TCP connection held; the charger is free
LINK_OPENING = Worker.OPENING  # opening the socket and logging in
LINK_IDLE = Worker.IDLE  # session held, nothing in flight
LINK_BUSY = Worker.BUSY  # a task is using the connection right now
LINK_ERROR = Worker.ERROR  # the last attempt failed; nothing is held

# How long a request thread waits for its turn.  Generous, because the task
# in front of it may be walking the whole transaction database.
DEFAULT_TASK_TIMEOUT_S = 180.0


class WorkerBusyError(AlfenError):
    """A task waited for its turn longer than the caller allowed.

    ``status`` is what the web server answers with: not a bad request --
    the request was fine -- but a conflict with whatever holds the charger.
    """

    status = HTTP_CONFLICT


class NotConnectedError(AlfenError):
    """No station has been selected yet."""


@dataclass
class Target:
    """Which charger to talk to, and as whom."""

    station: Station
    username: str
    password: str
    label: str = ""
    debug: bool = False

    @property
    def name(self) -> str:
        """A short name for the station, for the UI and the log."""
        return self.label or self.station.object_id or self.station.ip


class StationWorker(Worker[AlfenCharger]):
    """Owns the charger connection and runs every request against it."""

    thread_name = "alfen-station"
    task_timeout_s = DEFAULT_TASK_TIMEOUT_S
    poll_task_name = "Refreshing status"

    def __init__(
        self,
        target: Target | None,
        events: Broadcaster,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL_S,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT_S,
        charger_factory: Callable[[Target], AlfenCharger] | None = None,
    ) -> None:
        """Set up the worker; it does not connect until it has work."""
        super().__init__(events, poll_interval=poll_interval, idle_timeout=idle_timeout)
        self._factory = charger_factory or _default_charger
        self._target = target
        self._info: ChargerInfo | None = None
        self._family = ""

    # --- what the shared worker asks of a charger ---------------------------------

    def _check_ready(self) -> None:
        """Refuse a task when no station has been selected yet."""
        if self._target is None:
            raise NotConnectedError("no station selected")

    def _busy_error(self, name: str, timeout: float) -> BaseException:
        """Say which operation is in front of this one."""
        return WorkerBusyError(
            f"the charger is busy ({self._op or 'another operation'}); "
            f"'{name}' did not get its turn within {timeout:.0f}s"
        )

    def _opening_note(self) -> str:
        """Name the station while the session is being opened."""
        target = self._target
        return f"Connecting to {target.name}" if target else "Connecting"

    def _open_link(self) -> AlfenCharger:
        """Connect, log in, and read the nameplate once."""
        target = self._target
        if target is None:  # pragma: no cover - _check_ready ran first
            raise NotConnectedError("no station selected")
        charger = self._factory(target)
        try:
            charger.login()
            info = charger.basic_info()
        except BaseException:
            charger.close()
            raise
        self._info = info
        self._family = device_family(str(info.model or ""))
        self.events.publish(
            "info",
            {
                "objectId": info.object_id,
                "model": info.model,
                "firmware": info.firmware,
                "identity": info.identity,
                "family": self._family,
                "address": f"{target.station.ip}:{target.station.port}",
            },
            sticky=True,
        )
        return charger

    def _close_link(self, link: AlfenCharger) -> None:
        """Log out and drop the connection.

        The logout is skipped when the process is on its way out: it is one
        more round trip to a charger that is about to see the connection
        drop anyway, and the charger ends the session on either.
        """
        self._info = None
        if not self.stopping:
            try:
                link.logout()
            except Exception:  # noqa: BLE001 - a doomed connection is still closed
                pass
        try:
            link.close()
        except Exception:  # noqa: BLE001
            pass

    def _after_failure(self, exc: BaseException) -> None:
        """Drop the connection after a failure, so the next task starts clean.

        Anything that goes wrong mid-session can have left the charger's
        single connection in a state we cannot reason about, and reconnecting
        costs one login -- so we always start again rather than guess.
        """
        self._close("after an error", quiet=True)
        self._set_state(self.ERROR, error=describe(exc))

    def _details(self) -> dict[str, Any]:
        """Name the station on the link state the page draws."""
        return {"station": self._target.name if self._target else ""}

    # --- what this program adds ---------------------------------------------------

    @property
    def target(self) -> Target | None:
        """The station this worker talks to, if one has been selected."""
        return self._target

    def set_target(self, target: Target) -> None:
        """Point the worker at a different station, dropping the old link."""
        with self._lock:
            self._target = target
            self._release_requested = True
            self._info = None
            self._family = ""

    @property
    def info(self) -> ChargerInfo | None:
        """The identity read at connect time, if the link is up."""
        return self._info

    @property
    def is_ahp(self) -> bool:
        """Whether the connected charger is an AHP-family station."""
        return self._family == "AHP"


def _default_charger(target: Target) -> AlfenCharger:
    """Build the real charger client for a target."""
    return AlfenCharger(
        target.station, target.username, target.password, debug=target.debug
    )


__all__ = [
    "ACTIVITY_HISTORY",
    "DEFAULT_IDLE_TIMEOUT_S",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_TASK_TIMEOUT_S",
    "JOB_NOTIFY_INTERVAL_S",
    "JOB_RETENTION_S",
    "LINK_BUSY",
    "LINK_ERROR",
    "LINK_IDLE",
    "LINK_OPENING",
    "LINK_RELEASED",
    "LOOP_TICK_S",
    "MAX_POLL_INTERVAL_S",
    "MIN_POLL_INTERVAL_S",
    "STOP_JOIN_S",
    "Job",
    "NotConnectedError",
    "StationWorker",
    "Target",
    "WorkerBusyError",
]
