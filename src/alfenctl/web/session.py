"""The one connection to the charger, and everything that queues behind it.

The charger binds its login session to the TCP connection and serves only
ONE connection at a time (see :mod:`alfenctl.charger`).  So the server does
not let request handlers talk to it: every call is a task submitted to this
worker, which owns the single :class:`~alfenctl.charger.AlfenCharger` and
runs tasks one at a time on its own thread.

That serialisation is also what makes the link indicator honest.  The worker
is the only place the socket is used, so it can say exactly what is
happening -- connecting, idle, busy with *this*, N tasks waiting -- and
publish every transition to all browsers.

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

import itertools
import queue
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from alfenctl.charger import AlfenCharger, ChargerInfo
from alfenctl.discovery import Station
from alfenctl.errors import AlfenError
from alfenctl.firmware import device_family
from alfenctl.web.events import Broadcaster

# Link states, as published to the UI.
LINK_RELEASED = "released"  # no TCP connection held; the charger is free
LINK_CONNECTING = "connecting"  # opening the socket and logging in
LINK_IDLE = "idle"  # session held, nothing in flight
LINK_BUSY = "busy"  # a task is using the connection right now
LINK_ERROR = "error"  # the last attempt failed; nothing is held

# How often the live view refreshes while at least one browser is watching.
DEFAULT_POLL_INTERVAL_S = 3.0
MIN_POLL_INTERVAL_S = 1.0
MAX_POLL_INTERVAL_S = 60.0

# How long the session may sit unused before the worker hands the charger
# back.  Long enough that clicking around the UI does not reconnect
# constantly, short enough that a forgotten browser tab is not in the way.
DEFAULT_IDLE_TIMEOUT_S = 45.0

# How long a blocking request waits for its turn plus its own execution.
# A firmware upload can hold the worker for a minute, and a page that gave
# up at 30 s would report a failure that did not happen.
DEFAULT_TASK_TIMEOUT_S = 180.0

# How long the loop sleeps when it has nothing to do (also the granularity
# of the poll timer and the idle countdown).
LOOP_TICK_S = 0.25

# How many finished operations the activity ticker remembers.
ACTIVITY_HISTORY = 12

# Jobs older than this are forgotten once they have finished.
JOB_RETENTION_S = 900.0

# A firmware upload reports progress far more often than a browser needs to
# redraw; this is the shortest gap between two progress events for one job.
JOB_NOTIFY_INTERVAL_S = 0.25

# How long :meth:`StationWorker.stop` waits for the worker thread.  Short on
# purpose: this is the last thing between Ctrl+C and the shell prompt, and
# the worker may be parked in a read from a charger that will answer in its
# own time.  Long enough that an idle worker is joined properly, short
# enough that a busy one is simply left behind.
STOP_JOIN_S = 0.1

_job_ids = itertools.count(1)


class WorkerBusyError(AlfenError):
    """A task waited for its turn longer than the caller allowed."""


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
        """A human label for the station (its object id, or its address)."""
        return self.label or self.station.object_id or self.station.ip


@dataclass
class Job:
    """A long-running operation the UI follows rather than waits for."""

    id: int
    name: str
    state: str = "queued"  # queued | running | done | failed
    progress: float | None = None
    message: str = ""
    error: str = ""
    started: float = 0.0
    finished: float = 0.0
    result: dict[str, Any] = field(default_factory=dict)
    notify: Callable[["Job"], None] | None = field(default=None, repr=False)
    _last_notify: float = field(default=0.0, repr=False)

    def report(
        self,
        progress: float | None = None,
        message: str | None = None,
        *,
        force: bool = False,
    ) -> None:
        """Update the job's progress and tell the browsers, at most 4x a second."""
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        if message is not None and message != self.message:
            self.message = message
            force = True  # a new step is worth an immediate event
        now = time.monotonic()
        if not force and now - self._last_notify < JOB_NOTIFY_INTERVAL_S:
            return
        self._last_notify = now
        if self.notify is not None:
            self.notify(self)

    def as_dict(self) -> dict[str, Any]:
        """Render the job for the UI."""
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "elapsed": (self.finished or time.time()) - self.started
            if self.started
            else 0.0,
        } | ({"result": self.result} if self.result else {})


class _Task:
    """One unit of charger work, queued for the worker thread."""

    def __init__(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        job: Job | None = None,
        quiet: bool = False,
    ) -> None:
        """Prepare a task; ``quiet`` keeps polls out of the activity ticker."""
        self.name = name
        self.fn = fn
        self.job = job
        self.quiet = quiet
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class StationWorker:
    """Owns the charger connection and runs every request against it."""

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
        self.events = events
        self.poll_interval = poll_interval
        self.idle_timeout = idle_timeout
        self._factory = charger_factory or _default_charger
        self._target = target
        self._queue: queue.Queue[_Task | None] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._charger: AlfenCharger | None = None
        self._info: ChargerInfo | None = None
        self._family = ""
        self._live = False
        self._release_requested = False
        self._last_used = time.monotonic()
        self._last_poll = 0.0
        self._last_tick = 0
        self._state = LINK_RELEASED
        self._op = ""
        self._op_quiet = False
        self._op_progress: float | None = None
        self._op_note = ""
        self._last_progress = 0.0
        self._error = ""

        self._since = time.time()
        self._activity: deque[dict[str, Any]] = deque(maxlen=ACTIVITY_HISTORY)
        self._jobs: dict[int, Job] = {}
        self._poll_fn: Callable[[AlfenCharger], Any] | None = None

    # --- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        """Start the worker thread."""
        self._thread = threading.Thread(
            target=self._loop, name="alfen-station", daemon=True
        )
        self._thread.start()
        self._publish_link()

    def stop(self, timeout: float = STOP_JOIN_S) -> None:
        """Stop the worker and drop the connection.

        Returning quickly matters more than unwinding tidily: this is what
        Ctrl+C waits for, and the worker can be in the middle of an HTTP
        round trip to a charger on the far end of a slow link.  Closing the
        client from here does not interrupt a blocked read -- a socket
        closed under a thread parked in ``recv`` on Linux stays parked --
        so the thread is asked to stop, given ``timeout`` to notice, and
        then left to the interpreter, which is entitled to do that because
        it is a daemon thread with nothing to write down.

        The charger loses nothing by it.  Its session is bound to the TCP
        connection, so the process exiting frees the station exactly as a
        logout would; see :meth:`_close`, which skips the logout once
        stopping for the same reason.
        """
        self._stopping.set()
        self._queue.put(None)
        thread = self._thread
        if thread is not None and timeout > 0:
            thread.join(timeout=timeout)

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

    def set_poll(self, *, live: bool | None = None, interval: float | None = None):
        """Turn the live refresh on or off, and set its interval."""
        if interval is not None:
            self.poll_interval = max(
                MIN_POLL_INTERVAL_S, min(MAX_POLL_INTERVAL_S, float(interval))
            )
        if live is not None:
            self._live = bool(live)
            if live:
                self._last_poll = 0.0  # refresh at once rather than on the beat
        self._publish_link()

    def set_poll_fn(self, fn: Callable[[AlfenCharger], Any] | None) -> None:
        """Install what a live refresh actually reads (set by the API layer)."""
        self._poll_fn = fn

    @property
    def live(self) -> bool:
        """Whether the live refresh is running."""
        return self._live

    def release(self) -> None:
        """Ask the worker to hand the charger back as soon as it is free."""
        self._release_requested = True

    # --- submitting work ---------------------------------------------------------

    def run(
        self,
        name: str,
        fn: Callable[[AlfenCharger], Any],
        *,
        timeout: float = DEFAULT_TASK_TIMEOUT_S,
    ) -> Any:
        """Run ``fn`` against the charger and return its result.

        Blocks the calling (request) thread until the worker gets to it.
        Raises whatever ``fn`` raised, or :class:`WorkerBusyError` if the
        queue did not reach it in ``timeout`` seconds.
        """
        if self._target is None:
            raise NotConnectedError("no station selected")
        task = _Task(name, fn)
        self._queue.put(task)
        if not task.done.wait(timeout):
            raise WorkerBusyError(
                f"the charger is busy ({self._op or 'another operation'}); "
                f"'{name}' did not get its turn within {timeout:.0f}s"
            )
        if task.error is not None:
            raise task.error
        return task.result

    def start_job(self, name: str, fn: Callable[[AlfenCharger, Job], Any]) -> Job:
        """Queue a long operation and return its :class:`Job` immediately."""
        if self._target is None:
            raise NotConnectedError("no station selected")
        job = Job(id=next(_job_ids), name=name, notify=self._on_job_progress)
        with self._lock:
            self._jobs[job.id] = job
            self._forget_old_jobs()
        self._publish_job(job)
        self._queue.put(_Task(name, fn, job=job))
        return job

    def job(self, job_id: int) -> Job | None:
        """Look up one job by id."""
        with self._lock:
            return self._jobs.get(job_id)

    def jobs(self) -> list[dict[str, Any]]:
        """Every job the worker still remembers, oldest first."""
        with self._lock:
            return [job.as_dict() for job in sorted(self._jobs.values(), key=_job_key)]

    def _forget_old_jobs(self) -> None:
        """Drop finished jobs nobody is going to ask about any more."""
        cutoff = time.time() - JOB_RETENTION_S
        for job_id, job in list(self._jobs.items()):
            if job.finished and job.finished < cutoff:
                del self._jobs[job_id]

    # --- state reporting ---------------------------------------------------------

    def link_state(self) -> dict[str, Any]:
        """Build the link snapshot published to every browser."""
        with self._lock:
            countdown = None
            if self._state == LINK_IDLE and not self._live:
                left = self.idle_timeout - (time.monotonic() - self._last_used)
                countdown = max(0.0, round(left, 1))
            return {
                "state": self._state,
                "op": self._op,
                # Whether the connection is busy with something nobody asked
                # for.  The live refresh runs every few seconds and holds the
                # link for as long as it takes; a page that treated that the
                # same as a firmware upload would blink every control on it
                # on the beat.  See the UI's `useSteadyBusy`.
                "quiet": self._op_quiet,
                "progress": self._op_progress,
                # What the task running right now has got through, in its
                # own words -- "412 records, page 5".  Some long reads have
                # no honest denominator to make a percentage out of, and a
                # made-up one is worse than a count that is true.
                "note": self._op_note,
                "queued": max(0, self._queue.qsize()),
                "since": self._since,
                "error": self._error,
                "live": self._live,
                "pollInterval": self.poll_interval,
                "releaseIn": countdown,
                "idleTimeout": self.idle_timeout,
                "station": self._target.name if self._target else "",
                "activity": list(self._activity),
                "clients": self.events.subscriber_count,
            }

    def _publish_link(self) -> None:
        """Tell every browser what the link is doing."""
        self.events.publish("link", self.link_state(), sticky=True)

    def _on_job_progress(self, job: Job) -> None:
        """Mirror a running job's progress onto the link, and publish both."""
        with self._lock:
            self._op_progress = job.progress
        self._publish_job(job)
        self._publish_link()

    def _publish_job(self, job: Job) -> None:
        """Tell every browser about one job's progress."""
        self.events.publish("job", job.as_dict())

    def _set_state(
        self,
        state: str,
        op: str = "",
        *,
        error: str = "",
        progress: float | None = None,
        quiet: bool = False,
    ) -> None:
        """Move the link to a new state and publish it."""
        with self._lock:
            self._state = state
            self._op = op
            self._op_quiet = quiet
            self._op_progress = progress
            self._op_note = ""
            self._error = error

            self._since = time.time()
        self._publish_link()

    def progress(self, fraction: float | None = None, note: str = "") -> None:
        """Say how the task running right now is getting on.

        The counterpart to :meth:`Job.report` for work that is *not* a job:
        a read the browser is waiting on, which holds the connection for
        seconds while it pages a charger.  Without this the page has only
        the pill's "busy", which is the same thing it says for a write that
        lands in 150 ms -- so a transaction database that takes eight
        seconds to walk is indistinguishable from a hang.

        ``fraction`` is ``None`` where there is no honest denominator (the
        log and the transaction database are paged until they run out, and
        nothing knows how many pages that is), and ``note`` then carries
        what there *is* to say -- how much has arrived so far.

        Called from the worker thread, from inside the task it describes,
        and throttled: a page every few hundred milliseconds is more than a
        browser needs to redraw.
        """
        now = time.monotonic()
        if now - self._last_progress < JOB_NOTIFY_INTERVAL_S:
            return
        self._last_progress = now
        with self._lock:
            self._op_progress = fraction
            self._op_note = note
        self._publish_link()

    def _note_activity(self, name: str, seconds: float, ok: bool, detail: str) -> None:
        """Add one finished operation to the ticker."""
        with self._lock:
            self._activity.appendleft(
                {
                    "op": name,
                    "seconds": round(seconds, 3),
                    "ok": ok,
                    "at": time.time(),
                    "detail": detail,
                }
            )

    # --- the worker thread -------------------------------------------------------

    def _loop(self) -> None:
        """Run tasks one at a time, polling and releasing in the gaps."""
        while not self._stopping.is_set():
            try:
                task = self._queue.get(timeout=LOOP_TICK_S)
            except queue.Empty:
                task = None
            if task is None:
                if self._stopping.is_set():
                    break
                self._idle_work()
                continue
            self._run_task(task)
        self._close("shutting down")

    def _idle_work(self) -> None:
        """Between tasks: refresh the live view, or hand the charger back."""
        if self._release_requested:
            self._release_requested = False
            self._close("released")
            return
        now = time.monotonic()
        # Polling with no station selected would fail on every beat and turn
        # the link red for something the user has not asked for yet.
        if self._live and self._poll_fn is not None and self._target is not None:
            if now - self._last_poll >= self.poll_interval:
                self._last_poll = now
                self._run_task(_Task("Refreshing status", self._poll_fn, quiet=True))
            return
        if self._charger is not None and now - self._last_used >= self.idle_timeout:
            self._close("idle")
        elif self._state == LINK_IDLE and int(now) != self._last_tick:
            self._last_tick = int(now)
            self._publish_link()  # keep the release countdown moving

    def _run_task(self, task: _Task) -> None:
        """Run one task, reporting the link state around it."""
        if self._release_requested:
            self._release_requested = False
            self._close("released")
        started = time.monotonic()
        job = task.job
        if job is not None:
            job.state = "running"
            job.started = time.time()
            self._publish_job(job)
        try:
            charger = self._ensure(quiet=task.quiet)
            self._set_state(LINK_BUSY, task.name, quiet=task.quiet)
            if job is not None:
                task.result = task.fn(charger, job)
            else:
                task.result = task.fn(charger)
        except BaseException as exc:  # noqa: BLE001 - reported, never swallowed
            task.error = exc
            self._on_failure(exc)
            if job is not None:
                job.state = "failed"
                job.error = _describe(exc)
                job.finished = time.time()
                self._publish_job(job)
            if not task.quiet:
                self._note_activity(
                    task.name, time.monotonic() - started, False, _describe(exc)
                )
        else:
            if job is not None:
                job.state = "done"
                job.progress = 1.0
                job.finished = time.time()
                self._publish_job(job)
            if not task.quiet:
                self._note_activity(task.name, time.monotonic() - started, True, "")
        finally:
            task.done.set()
            self._last_used = time.monotonic()
            if self._charger is not None:
                self._set_state(LINK_IDLE)

    def _ensure(self, *, quiet: bool = False) -> AlfenCharger:
        """Return the live charger, connecting and logging in if needed."""
        if self._charger is not None:
            return self._charger
        target = self._target
        if target is None:
            raise NotConnectedError("no station selected")
        self._set_state(LINK_CONNECTING, f"Connecting to {target.name}", quiet=quiet)
        charger = self._factory(target)
        try:
            charger.login()
            info = charger.basic_info()
        except BaseException:
            charger.close()
            raise
        self._charger = charger
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

    def _on_failure(self, exc: BaseException) -> None:
        """Drop the connection after a failure, so the next task starts clean.

        Anything that goes wrong mid-session can have left the charger's
        single connection in a state we cannot reason about, and reconnecting
        costs one login -- so we always start again rather than guess.
        """
        self._close("after an error", quiet=True)
        self._set_state(LINK_ERROR, error=_describe(exc))

    def _close(self, why: str, *, quiet: bool = False) -> None:
        """Log out and drop the connection, if one is held.

        The logout is skipped when the process is on its way out: it is one
        more round trip to a charger that is about to see the connection
        drop anyway, and the charger ends the session on either.
        """
        charger = self._charger
        self._charger = None
        self._info = None
        if charger is not None:
            if not self._stopping.is_set():
                try:
                    charger.logout()
                except Exception:  # noqa: BLE001 - a doomed connection is still closed
                    pass
            try:
                charger.close()
            except Exception:  # noqa: BLE001
                pass
        if not quiet:
            self._set_state(LINK_RELEASED, why if charger is not None else "")

    # --- convenience for the API layer -------------------------------------------

    @property
    def info(self) -> ChargerInfo | None:
        """The identity read at connect time, if the link is up."""
        return self._info

    @property
    def is_ahp(self) -> bool:
        """Whether the connected charger is an AHP-family station."""
        return self._family == "AHP"


def _job_key(job: Job) -> tuple[float, int]:
    """Sort jobs by start time, then id (queued ones have no start time)."""
    return (job.started or float("inf"), job.id)


def _default_charger(target: Target) -> AlfenCharger:
    """Build the real charger client for a target."""
    return AlfenCharger(
        target.station, target.username, target.password, debug=target.debug
    )


def _describe(exc: BaseException) -> str:
    """One readable line for an exception, for the UI and the ticker."""
    text = str(exc).strip()
    if not text:
        text = exc.__class__.__name__
    elif exc.__class__.__name__ not in ("RuntimeError", "ValueError"):
        text = f"{exc.__class__.__name__}: {text}"
    return text.splitlines()[0][:400]


def format_traceback(exc: BaseException) -> str:
    """Full traceback text, for --debug logging of a failed task."""
    return "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    ).strip()
