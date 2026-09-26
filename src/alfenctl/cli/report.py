"""An upgrade's progress on a terminal: the upload bar and the reboot wait.

The scaffolding -- the one live stderr line, the decision not to draw it
into a pipe, closing it off when a failure lands on top of it -- is
:class:`devicectl.cli.report.TerminalReporter`.  What is here is what an
Alfen upgrade counts: megabytes uploaded, and a reboot that has to be polled
for until the charger answers again.
"""

from __future__ import annotations

import sys
import time

from devicectl.cli.report import TerminalReporter as _Terminal
from devicectl.progress import (
    BYTES_PER_MB,
    PROGRESS_MIN_INTERVAL_S,
    bar,
    fmt_duration,
)
from devicectl.report import Wait

from alfenctl.charger import AlfenCharger
from alfenctl.upgrade import wait_until_back


class TerminalReporter(_Terminal):
    """Report an upgrade's progress to the terminal.

    Use it as a context manager: leaving the block closes off a live line
    that a failure would otherwise have left half-drawn, with the error
    message landing on top of it.
    """

    def __init__(self, *, debug: bool = False) -> None:
        """Report to stderr, drawing a live line unless ``debug`` or a pipe."""
        super().__init__(quiet=debug)
        self.debug = debug
        self._logged_poll = 0

    # --- what the upgrade tells us ---------------------------------------------------------

    def sending(self, sent: int, total: int, elapsed_s: float, label: str = "") -> None:
        """Redraw the transfer bar, at most every PROGRESS_MIN_INTERVAL_S.

        ``label`` is what is moving -- a file name for a download, nothing
        for the one upload an upgrade makes, which the phase above already
        named.
        """
        now = time.monotonic()
        if sent < total and now - self._last_draw < PROGRESS_MIN_INTERVAL_S:
            return  # throttle mid-stream redraws, but always draw the final 100%
        self._last_draw = now
        frac = sent / total if total else 1.0
        eta = elapsed_s * (total - sent) / sent if sent else 0.0
        counted = (
            f"{sent / BYTES_PER_MB:.1f}/{total / BYTES_PER_MB:.1f} MB"
            if total
            else f"{sent / BYTES_PER_MB:.1f} MB"
        )
        shown = f"[{bar(frac)}] {frac:4.0%}  " if total else ""
        self._draw(
            f"  {label or 'Uploading'}  {shown}{counted}  "
            f"elapsed {fmt_duration(elapsed_s)}  eta {fmt_duration(eta)}"
        )

    def waiting(self, wait: Wait) -> None:
        """Redraw the reboot line, countdown included."""
        countdown = (
            f"  next poll in {int(wait.next_poll_in_s) + 1}s"
            if wait.next_poll_in_s is not None
            else ""
        )
        self._draw(
            f"  Rebooting  poll {wait.poll}  status: {wait.label}  "
            f"{_elapsed_text(wait)}{countdown}"
        )

    def polled(self, wait: Wait) -> None:
        """Record a completed poll on the outputs that have no live line."""
        if self.live or wait.poll == self._logged_poll:
            return  # the live line already shows it
        self._logged_poll = wait.poll
        if self.debug:
            print(
                f"[debug] -- reboot wait: poll {wait.poll}, status {wait.label}, "
                f"elapsed {fmt_duration(wait.elapsed_s)}, "
                f"next poll in {int(wait.next_poll_in_s or 0)}s",
                file=sys.stderr,
            )
        else:
            print(
                f"  poll {wait.poll}: {wait.label}  "
                f"(elapsed {fmt_duration(wait.elapsed_s)})"
            )


def _elapsed_text(wait: Wait) -> str:
    """Elapsed time, against the duration this normally takes.

    Past the typical duration the deadline is named too: a two-minute
    reboot that has run for five minutes has not hung, and the line should
    say when we will stop believing that.
    """
    if wait.elapsed_s <= wait.typical_s:
        return (
            f"elapsed {fmt_duration(wait.elapsed_s)} / ~{fmt_duration(wait.typical_s)}"
        )
    return (
        f"elapsed {fmt_duration(wait.elapsed_s)} (usually ~"
        f"{fmt_duration(wait.typical_s)}; giving up at "
        f"{fmt_duration(wait.deadline_s)})"
    )


def wait_for_reboot(
    charger: AlfenCharger, *, deadline_s: float, debug: bool = False
) -> bool:
    """Wait for a charger that was just restarted, showing the wait as it goes.

    Three commands reboot a charger and then wait for it; this is that wait
    with a progress line attached.  Returns False if it never came back.
    """
    with TerminalReporter(debug=debug) as report:
        return wait_until_back(charger, report=report, deadline_s=deadline_s)
