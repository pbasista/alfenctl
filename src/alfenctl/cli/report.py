"""Progress on a terminal: one live line that rewrites itself.

The upload bar and the reboot countdown are the same idea -- a single
stderr line, redrawn as things move, ended with a newline when the phase
is over.  Two things turn the live line off: a pipe (nothing would ever
erase the escape codes) and ``--debug``, whose log lines would shred it.
Both fall back to plain lines, which is also what a log file wants.
"""

from __future__ import annotations

import sys
import time
from types import TracebackType

from alfenctl.progress import (
    BYTES_PER_MB,
    PROGRESS_MIN_INTERVAL_S,
    bar,
    end_live,
    fmt_duration,
    write_live,
)
from alfenctl.charger import AlfenCharger
from alfenctl.report import Reporter, Wait
from alfenctl.upgrade import wait_until_back


class TerminalReporter(Reporter):
    """Reports an upgrade's progress to the terminal.

    Use it as a context manager: leaving the block closes off a live line
    that a failure would otherwise have left half-drawn, with the error
    message landing on top of it.
    """

    def __init__(self, *, debug: bool = False) -> None:
        """Report to stderr, drawing a live line unless ``debug`` or a pipe."""
        self.debug = debug
        self.live = not debug and sys.stderr.isatty()
        self._drawn = False  # a live line is on screen, awaiting its newline
        self._last_draw = 0.0
        self._logged_poll = 0

    def __enter__(self) -> TerminalReporter:
        """Return the reporter; nothing is drawn until something happens."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """End any live line, so the next thing printed starts on its own."""
        self._close()

    def _close(self) -> None:
        """Finish the live line, if one is on screen."""
        if self._drawn:
            end_live()
            self._drawn = False

    def _draw(self, text: str) -> None:
        """Put ``text`` on the live line (no-op when there is no live line)."""
        if not self.live:
            return
        write_live(text)
        self._drawn = True

    # --- what the upgrade tells us ---------------------------------------------------------

    def step(self, message: str) -> None:
        """Print the new phase on a line of its own."""
        self._close()
        print(f"{message}...")

    def detail(self, message: str) -> None:
        """Print a detail, indented under the phase it belongs to."""
        self._close()
        print(f"  {message}")

    def warn(self, message: str) -> None:
        """Print a warning to stderr."""
        self._close()
        print(f"warning: {message}", file=sys.stderr)

    def sending(self, sent: int, total: int, elapsed_s: float) -> None:
        """Redraw the upload bar, at most every PROGRESS_MIN_INTERVAL_S."""
        now = time.monotonic()
        if sent < total and now - self._last_draw < PROGRESS_MIN_INTERVAL_S:
            return  # throttle mid-stream redraws, but always draw the final 100%
        self._last_draw = now
        frac = sent / total if total else 1.0
        eta = elapsed_s * (total - sent) / sent if sent else 0.0
        self._draw(
            f"  Uploading  [{bar(frac)}] {frac:4.0%}  "
            f"{sent / BYTES_PER_MB:.1f}/{total / BYTES_PER_MB:.1f} MB  "
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
