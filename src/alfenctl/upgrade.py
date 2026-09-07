"""The end-to-end firmware upgrade sequence (the app's ``ICULanDevice.StartUpload``).

What happens once an image has been chosen and checked -- steps 3 to 7 of
the app's upload dialog:

1. Set the charger clock -- signature validation checks certificate
   validity against it.
2. Abort if an upload is already in progress.
3. Upload the image (see :meth:`AlfenCharger.upload_firmware
   <alfenctl.charger.AlfenCharger.upload_firmware>`).
4. Poll ``GET /api/firmware`` through the charger's own reboot (it applies
   the firmware and restarts itself; no reboot command is sent) until a
   terminal state.
5. Commit with ``forcefirmwarepermanent`` so the new firmware is kept, not
   rolled back -- and set the new unique password when the upgrade crossed
   the 5.0 boundary.

Choosing the image, checking it against the charger and asking the user to
confirm all happen in front of this, in whichever front end is driving:
:mod:`alfenctl.cli.commands.firmware` for the CLI, :mod:`alfenctl.web.api`
for the browser.  Nothing here prints; progress goes to a
:class:`~alfenctl.report.Reporter`, and a failure is raised.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Iterator

import httpx

from alfenctl.charger import REBOOT_POLL_TIMEOUT_S, AlfenCharger
from alfenctl.errors import AlfenError
from alfenctl.firmware import FW_STATUS, FW_TERMINAL_ERR, FW_TERMINAL_OK
from alfenctl.progress import PROGRESS_TICK_S
from alfenctl.report import SILENT, Reporter, Wait

# Seconds between /api/firmware polls while waiting for the install.
DEFAULT_POLL_INTERVAL_S = 5.0
# Give-up deadline for the install+reboot phase -- NOT an estimate of how
# long it takes.  It is the app's own cap: ``ICULanDevice.StartUpload``
# fails the update with "it took too long!" past 900 s
# (``s_nFirmwareUploadTimeout``).
DEFAULT_INSTALL_TIMEOUT_S = 900.0
# How long the install+reboot actually takes.  The same app loop stops
# treating the charger as rebooting after 170 s ("Reset timeout was
# reached"), which matches the ~2-3 minutes observed on a live NG910-60027.
# Shown to set expectations; nothing is decided by it.
TYPICAL_INSTALL_S = 170.0
# How long a plain reboot takes.  The app's reboot dialog fills its bar in
# 480 ticks of 250 ms (``OnRebootProgress``), i.e. it is drawn for 2 minutes.
TYPICAL_REBOOT_S = 120.0
# Give-up deadline for a plain reboot.
DEFAULT_REBOOT_TIMEOUT_S = 300.0
# Seconds to let writes settle before pulling the rug: the app counts down
# to 5 s after the last property write or file upload
# (``GetRebootDelayInMillis``) before it sends the reboot.
REBOOT_SETTLE_S = 5.0
# Measured upload throughput on a live NG910 (1.82 MB accepted in ~97 s
# ~= 18.7 KB/s). Used only to estimate the upload duration up front; kept
# slightly conservative so the estimate isn't rosy.
UPLOAD_THROUGHPUT_BYTES_PER_S = 18000


class UpgradeError(AlfenError):
    """The upgrade could not be carried out."""


class UploadInProgress(UpgradeError):
    """The charger is already taking an upload, so it will not take ours."""


class InstallFailed(UpgradeError):
    """The upload was accepted, but the install never reached a good state."""


# --- Sending an image ---------------------------------------------------------------------


def send_image(
    charger: AlfenCharger,
    image: bytes,
    *,
    report: Reporter = SILENT,
    label: str = "Uploading",
    is_ahp: bool = False,
) -> None:
    """Push one image through the charger's firmware channel.

    Firmware images and splash-logo packages take the same route (``POST
    /api/firmware``); only the follow-up differs -- see :mod:`alfenctl.logo`.
    The clock is set first because signature validation checks the
    certificate against it, and a charger that is already taking an upload
    will not take a second one.
    """
    report.step("Setting the charger clock")
    charger.set_datetime(is_ahp=is_ahp)
    in_progress, _ = charger.firmware_status()
    if in_progress:
        raise UploadInProgress("an upload is already in progress on this charger")
    report.step(label)
    charger.on_upload_progress = report.sending
    try:
        charger.upload_firmware(image)
    finally:
        charger.on_upload_progress = None
    report.detail("Upload accepted")


def install(
    charger: AlfenCharger,
    image: bytes,
    *,
    report: Reporter = SILENT,
    new_password: str | None = None,
    deadline_s: float = DEFAULT_INSTALL_TIMEOUT_S,
    interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> None:
    """Upload a firmware image, wait out the charger's reboot, and commit it.

    ``charger`` may be logged out on return and in again by the time this
    finishes: the session does not survive the reboot, so the commit logs in
    again.  Raises :class:`UploadInProgress` or :class:`InstallFailed`; a
    commit or password step that fails is only reported, because by then the
    firmware is already installed.
    """
    send_image(charger, image, report=report, label="Uploading firmware")
    report.step("Installing and rebooting")
    poll_until_done(
        charger, report=report, deadline_s=deadline_s, interval_s=interval_s
    )

    report.step("Committing the firmware (forcefirmwarepermanent)")
    try:
        charger.login()  # the session is lost across the reboot
        charger.commit_firmware()
    except httpx.HTTPError as exc:
        report.warn(f"could not send the commit command: {exc}")

    if new_password:
        # The app sets the new password right after forcefirmwarepermanent
        # (ICULanDevice.ChangePassword), for upgrades across the 5.0 boundary.
        report.step("Setting the new charger password")
        try:
            charger.set_password(new_password)
        except httpx.HTTPError as exc:
            report.warn(
                f"could not set the new password: {exc}. There is probably "
                "already a password present; use that to log in to the device."
            )


# --- Waiting for the charger --------------------------------------------------------------


Answer = tuple[bool, int] | None  # (upload in progress, status); None: no reply


class _Poll:
    """One ``firmware_status`` call, run on a daemon thread.

    The thread is what lets the progress line keep ticking through a request
    that blocks; it is a daemon so a charger that never answers cannot hold
    up interpreter exit.

    A failed poll is not followed by an explicit re-login. The session dies
    with the connection across the reboot, so the charger answers the *next*
    poll with 401 and :meth:`AlfenCharger._authed` re-authenticates and
    retries there -- on the same short timeout. Logging in here as well only
    doubled what a poll costs while the charger is still down, since that
    login cannot succeed either.
    """

    def __init__(self, charger: AlfenCharger, timeout: float) -> None:
        self.outcome: Answer = None  # None: no answer
        self._thread = threading.Thread(
            target=self._run, args=(charger, timeout), daemon=True
        )
        self._thread.start()

    def _run(self, charger: AlfenCharger, timeout: float) -> None:
        try:
            self.outcome = charger.firmware_status(timeout=timeout)
        except httpx.HTTPError:
            pass  # no answer: the charger is still installing/rebooting

    def done(self) -> bool:
        """Report whether the request has finished, one way or the other."""
        return not self._thread.is_alive()


class Watch:
    """Polls the charger until something is decided, or the deadline passes.

    Iterating yields one :data:`Answer` per poll and stops at the deadline;
    the loop body works out what the answer meant and passes that back with
    :meth:`say`, which is what the progress line shows until the next poll
    comes back.

    The waiting is the interesting part.  A charger that is rebooting leaves
    the request hanging until it times out, so the polls run on daemon
    threads (:class:`_Poll`) and every wait here -- for the answer, and then
    for the poll interval -- ticks the reporter as it passes.  A countdown
    frozen at "next poll in 1s" reads like a hang.
    """

    def __init__(
        self,
        charger: AlfenCharger,
        *,
        report: Reporter,
        deadline_s: float,
        typical_s: float,
        interval_s: float,
    ) -> None:
        """Start the clock on a wait of at most ``deadline_s`` seconds."""
        self.charger = charger
        self.report = report
        self.deadline_s = deadline_s
        self.typical_s = typical_s
        self.interval_s = interval_s
        self.start = time.monotonic()
        self.poll = 0
        self.label = "polling..."

    def elapsed(self) -> float:
        """Seconds since the wait began."""
        return time.monotonic() - self.start

    def expired(self) -> bool:
        """Report whether the give-up deadline has passed."""
        return self.elapsed() >= self.deadline_s

    def say(self, label: str) -> None:
        """Record what the poll that just came back meant."""
        self.label = label
        self.report.polled(self._wait(self.interval_s))

    def _wait(self, next_poll_in_s: float | None) -> Wait:
        return Wait(
            elapsed_s=self.elapsed(),
            deadline_s=self.deadline_s,
            typical_s=self.typical_s,
            label=self.label,
            poll=self.poll,
            next_poll_in_s=next_poll_in_s,
        )

    def _tick(self, ready: Callable[[], bool], limit_s: float | None = None) -> None:
        """Wait for ``ready()`` (or ``limit_s``), reporting as the time passes.

        Also returns as soon as the give-up deadline passes, so a poll that
        never comes back cannot hold the upgrade open past it.
        """
        began = time.monotonic()
        while not ready() and not self.expired():
            waited = time.monotonic() - began
            if limit_s is not None and waited >= limit_s:
                return
            self.report.waiting(
                self._wait(None if limit_s is None else limit_s - waited)
            )
            time.sleep(PROGRESS_TICK_S)

    def __iter__(self) -> Iterator[Answer]:
        """Yield each poll's answer until the deadline passes."""
        while not self.expired():
            self.poll += 1
            self.label = "polling..."
            call = _Poll(self.charger, REBOOT_POLL_TIMEOUT_S)
            self._tick(call.done)
            if not call.done():
                return  # the deadline passed with a poll still in flight
            yield call.outcome
            self._tick(lambda: False, limit_s=self.interval_s)


def poll_until_done(
    charger: AlfenCharger,
    *,
    report: Reporter = SILENT,
    deadline_s: float = DEFAULT_INSTALL_TIMEOUT_S,
    interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> None:
    """Poll GET /api/firmware through the install/reboot until a terminal state.

    Mirrors ``ICULanDevice.StartUpload``. After a full-image upload the
    charger reboots itself to apply the firmware (the app never sends a
    reboot command -- it just tracks the web server going down and coming
    back), so a failure to answer means "still rebooting" and we keep
    waiting.

    The charger keeps its LAST update status around (it can already read
    UPDATE_DONE/NO_ACTIVE_UPDATE before our image is even processed), so a
    terminal status only counts as OURS once we have actually seen the
    charger do the update: a reboot (web server dropped), an
    in-progress/download status, or a transition away from whatever status
    it was showing when we started.

    Returns when the update reached a good terminal state; raises
    :class:`InstallFailed` on a terminal error or the deadline.
    """
    watch = Watch(
        charger,
        report=report,
        deadline_s=deadline_s,
        typical_s=TYPICAL_INSTALL_S,
        interval_s=interval_s,
    )
    initial: int | None = None  # the (stale) status reported on our first read
    saw_reboot = False  # the web server went away -> it is installing/rebooting
    saw_active = False  # we saw the update progress (a reboot, or a moved status)
    for answer in watch:
        if answer is None:
            saw_reboot = True
            watch.say("no response (rebooting)")
            continue
        in_progress, status = answer
        if initial is None:
            initial = status
        label = FW_STATUS.get(status, str(status)) + (
            "  (upload in progress)" if in_progress else ""
        )
        if status in FW_TERMINAL_ERR:
            raise InstallFailed(f"the charger reported {label}")
        if in_progress or status not in FW_TERMINAL_OK or status != initial:
            saw_active = True
        if status in FW_TERMINAL_OK and not in_progress and (saw_reboot or saw_active):
            report.detail(f"status: {label}")  # done, after the update really ran
            return
        watch.say(label)
    raise InstallFailed("the charger did not come back after the firmware upload")


def wait_until_back(
    charger: AlfenCharger,
    *,
    report: Reporter = SILENT,
    deadline_s: float = DEFAULT_REBOOT_TIMEOUT_S,
    typical_s: float = TYPICAL_REBOOT_S,
    interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> bool:
    """Wait for a charger that was just told to restart to answer again.

    The charger keeps answering for a moment after it accepts the command,
    so "it responds" is not yet proof of anything: we wait to see it *go
    away* first, and only then treat an answer as the reboot having
    completed. Returns False if it never went away, or never came back
    before the deadline.
    """
    watch = Watch(
        charger,
        report=report,
        deadline_s=deadline_s,
        typical_s=typical_s,
        interval_s=interval_s,
    )
    went_down = False
    for answer in watch:
        if answer is None:
            went_down = True
            watch.say("no response (rebooting)")
        elif went_down:
            report.detail("the charger is back")
            return True
        else:
            watch.say("still answering (not down yet)")
    return False
