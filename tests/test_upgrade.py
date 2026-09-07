"""Tests for the upgrade sequence, driven by a fake charger.

Nothing here looks at output: :mod:`alfenctl.upgrade` reports to a
:class:`~alfenctl.report.Reporter`, so what it says is checked by reading
the recorder below.  What the CLI *prints* is tested in test_cli_firmware.
"""

from __future__ import annotations

import time

import httpx
import pytest

import alfenctl.upgrade as upgrade_mod
from alfenctl.charger import ChargerInfo
from alfenctl.firmware import FW_UPDATE_DONE
from alfenctl.report import Reporter, Wait
from alfenctl.upgrade import InstallFailed, UploadInProgress, install, send_image

INFO = ChargerInfo(
    object_id="ACE0781464",
    identity="ACE0781464",
    model="NG910-60027",
    family="NG",
    firmware="7.4.5-4415",
    firmware_version=(7, 4, 5),
    sockets=1,
)

IMAGE = b"FIRMWARE-IMAGE"


class Recorder(Reporter):
    """A reporter that remembers what it was told, in order."""

    def __init__(self) -> None:
        self.steps: list[str] = []
        self.details: list[str] = []
        self.warnings: list[str] = []
        self.waits: list[Wait] = []

    def step(self, message: str) -> None:
        self.steps.append(message)

    def detail(self, message: str) -> None:
        self.details.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def polled(self, wait: Wait) -> None:
        self.waits.append(wait)


class FakeCharger:
    """Records the calls the upgrade makes, answering like an idle charger."""

    def __init__(self, *, in_progress: bool = False) -> None:
        self.debug = False
        self.calls: list[str] = []
        self.in_progress = in_progress
        self.on_upload_progress = None
        self.commit_error: httpx.HTTPError | None = None

    def login(self) -> None:
        self.calls.append("login")

    def basic_info(self) -> ChargerInfo:
        self.calls.append("basic_info")
        return INFO

    def set_datetime(self, is_ahp: bool = False, when=None):
        self.calls.append(f"set_datetime(is_ahp={is_ahp})")

    def firmware_status(self, timeout: float | None = None) -> tuple[bool, int]:
        self.calls.append("firmware_status")
        return self.in_progress, FW_UPDATE_DONE

    def upload_firmware(self, data: bytes) -> None:
        self.calls.append("upload_firmware")
        if self.on_upload_progress is not None:
            self.on_upload_progress(len(data), len(data), 1.0)

    def commit_firmware(self) -> None:
        self.calls.append("commit_firmware")
        if self.commit_error is not None:
            raise self.commit_error

    def set_password(self, new_password: str) -> None:
        self.calls.append("set_password")


@pytest.fixture
def instant(monkeypatch):
    """Make the install wait return at once, so the sequence tests stay fast."""
    monkeypatch.setattr(upgrade_mod, "poll_until_done", lambda charger, **kw: None)


# --- Sending an image ----------------------------------------------------------------------


def test_send_image_sets_the_clock_before_uploading() -> None:
    charger = FakeCharger()
    report = Recorder()

    send_image(charger, IMAGE, report=report, label="Uploading firmware")

    # The app's order: clock, then the in-progress check, then the image.
    assert charger.calls == [
        "set_datetime(is_ahp=False)",
        "firmware_status",
        "upload_firmware",
    ]
    assert report.steps == ["Setting the charger clock", "Uploading firmware"]


def test_send_image_tells_an_ahp_charger_apart() -> None:
    charger = FakeCharger()
    send_image(charger, IMAGE, is_ahp=True)
    assert "set_datetime(is_ahp=True)" in charger.calls


def test_send_image_refuses_when_an_upload_is_already_running() -> None:
    charger = FakeCharger(in_progress=True)
    with pytest.raises(UploadInProgress, match="already in progress"):
        send_image(charger, IMAGE)
    assert "upload_firmware" not in charger.calls


def test_send_image_takes_the_progress_hook_back_afterwards() -> None:
    """A left-behind callback would report the next upload to the wrong place."""
    charger = FakeCharger()
    send_image(charger, IMAGE, report=Recorder())
    assert charger.on_upload_progress is None


# --- The whole install ---------------------------------------------------------------------


def test_install_uploads_commits_then_sets_the_password(instant) -> None:
    charger = FakeCharger()
    report = Recorder()

    install(charger, IMAGE, report=report, new_password="hunter2")

    order = charger.calls
    assert order.index("firmware_status") < order.index("upload_firmware")
    assert order.index("upload_firmware") < order.index("commit_firmware")
    assert order.index("commit_firmware") < order.index("set_password")
    # The commit needs a session of its own: the reboot took the old one.
    assert order.index("login") == order.index("commit_firmware") - 1
    assert not report.warnings


def test_install_without_a_new_password_skips_it(instant) -> None:
    charger = FakeCharger()
    install(charger, IMAGE)
    assert "set_password" not in charger.calls


def test_install_only_warns_when_the_commit_fails(instant) -> None:
    """The firmware is already on by then; a failed commit is not a failure."""
    charger = FakeCharger()
    charger.commit_error = httpx.ConnectError("connection refused")
    report = Recorder()

    install(charger, IMAGE, report=report)

    assert report.warnings and "commit" in report.warnings[0]


def test_install_stops_before_committing_if_the_install_failed(monkeypatch) -> None:
    def boom(charger, **kw):
        raise InstallFailed("the charger reported update error")

    monkeypatch.setattr(upgrade_mod, "poll_until_done", boom)
    charger = FakeCharger()

    with pytest.raises(InstallFailed):
        install(charger, IMAGE)
    assert "commit_firmware" not in charger.calls


# --- Reboot polling ---------------------------------------------------------------------


class PollCharger:
    """A charger whose /api/firmware answers are scripted, one per poll."""

    debug = False

    def __init__(self, answers: list[object], *, block_s: float = 0.0) -> None:
        self.answers = list(answers)  # tuple => reply; Exception => no answer
        self.block_s = block_s  # how long each call sits there before answering
        self.polls = 0
        self.logins = 0

    def firmware_status(self, timeout: float | None = None) -> tuple[bool, int]:
        self.polls += 1
        assert timeout is not None, "reboot polls must not use the 30 s default"
        if self.block_s:
            time.sleep(min(self.block_s, timeout))
        answer = self.answers.pop(0) if self.answers else (False, FW_UPDATE_DONE)
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[return-value]

    def login(self, timeout: float | None = None) -> None:
        self.logins += 1


FW_ERROR_DURING_UPDATE = -2
DOWN = httpx.ConnectError("connection refused")


@pytest.fixture
def brisk(monkeypatch):
    """Shorten the display tick so a poll loop runs in milliseconds."""
    monkeypatch.setattr(upgrade_mod, "PROGRESS_TICK_S", 0.001)


def test_poll_until_done_waits_through_the_reboot(brisk) -> None:
    """A charger that goes away and comes back as DONE is a success."""
    charger = PollCharger([DOWN, DOWN, (False, FW_UPDATE_DONE)])
    upgrade_mod.poll_until_done(charger, deadline_s=30, interval_s=0.01)
    assert charger.polls == 3
    # No re-login of its own: the session comes back through the 401 the
    # charger answers the next poll with, inside _authed (see test_charger).
    assert charger.logins == 0


def test_poll_until_done_ignores_a_stale_terminal_status(brisk) -> None:
    """The charger reports the PREVIOUS update as done before ours even starts."""
    charger = PollCharger(
        [
            (False, FW_UPDATE_DONE),  # stale: nothing has happened yet
            DOWN,  # now it actually reboots
            (False, FW_UPDATE_DONE),  # this one is ours
        ]
    )
    upgrade_mod.poll_until_done(charger, deadline_s=30, interval_s=0.01)
    assert charger.polls == 3


def test_poll_until_done_reports_a_terminal_error(brisk) -> None:
    charger = PollCharger([(False, FW_ERROR_DURING_UPDATE)])
    with pytest.raises(InstallFailed, match="the charger reported"):
        upgrade_mod.poll_until_done(charger, deadline_s=30, interval_s=0.01)


def test_poll_until_done_gives_up_at_the_deadline(brisk) -> None:
    charger = PollCharger([DOWN] * 100)
    with pytest.raises(InstallFailed, match="did not come back"):
        upgrade_mod.poll_until_done(charger, deadline_s=0.15, interval_s=0.01)


def test_poll_keeps_reporting_while_a_poll_blocks(monkeypatch) -> None:
    """The freeze case: a rebooting charger leaves the request hanging.

    The wait has to keep reporting (with a live elapsed time) for the whole
    time the request is in flight, not just between polls.
    """
    monkeypatch.setattr(upgrade_mod, "PROGRESS_TICK_S", 0.005)
    ticks: list[Wait] = []

    class Ticks(Reporter):
        def waiting(self, wait: Wait) -> None:
            ticks.append(wait)

    # One poll that sits blocked for 0.2 s, then a clean answer.
    charger = PollCharger([DOWN, (False, FW_UPDATE_DONE)], block_s=0.2)
    upgrade_mod.poll_until_done(charger, report=Ticks(), deadline_s=30, interval_s=0.01)
    in_flight = [w for w in ticks if w.next_poll_in_s is None]
    # ~0.2 s blocked at a 0.005 s tick: reported all the way through, not once.
    assert len(in_flight) > 5
    assert all(w.label == "polling..." for w in in_flight)
    # It counts down between polls too, not only during them.
    assert any(w.next_poll_in_s is not None for w in ticks)


def test_a_wait_carries_what_it_takes_to_draw_it(brisk) -> None:
    charger = PollCharger([DOWN, (False, FW_UPDATE_DONE)])
    report = Recorder()
    upgrade_mod.poll_until_done(charger, report=report, deadline_s=30, interval_s=0.01)
    first = report.waits[0]
    assert first.poll == 1
    assert first.label == "no response (rebooting)"
    assert first.deadline_s == 30
    assert first.typical_s == upgrade_mod.TYPICAL_INSTALL_S


# --- Waiting out a plain reboot --------------------------------------------------------------


def test_wait_until_back_needs_to_see_it_go_down_first(brisk) -> None:
    """A charger still answering has not rebooted yet, however healthy it looks."""
    charger = PollCharger([(False, FW_UPDATE_DONE), DOWN, (False, FW_UPDATE_DONE)])
    assert upgrade_mod.wait_until_back(charger, deadline_s=30, interval_s=0.01)
    assert charger.polls == 3


def test_wait_until_back_gives_up_if_it_never_returns(brisk) -> None:
    charger = PollCharger([DOWN] * 100)
    assert not upgrade_mod.wait_until_back(charger, deadline_s=0.15, interval_s=0.01)
