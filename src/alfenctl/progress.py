"""Terminal progress rendering for the (slow) upload and reboot wait.

Plain stderr ``#``/``-`` bars carrying a percentage, elapsed time and an
estimated remaining time. The live-updating single line is used only when
stderr is a TTY; in ``--debug`` mode the callers log discrete lines instead
(no bar). No progress-bar dependency -- a few dozen lines do the job.
"""

from __future__ import annotations

import sys

# Width, in characters, of the textual progress bar.
PROGRESS_BAR_WIDTH = 24
# Don't redraw the upload bar more often than this; smooths the fast initial
# buffer-fill burst.
PROGRESS_MIN_INTERVAL_S = 0.1
# Granularity of the reboot-wait countdown.
PROGRESS_TICK_S = 1.0
# In debug mode we don't draw a live bar; instead the upload logs a progress
# line each time this fraction of the body has gone by (0.1 -> every ~10%).
PROGRESS_DEBUG_STEP = 0.1

BYTES_PER_KB = 1000
BYTES_PER_MB = 1_000_000
SECONDS_PER_MINUTE = 60


def fmt_duration(seconds: float) -> str:
    """Format a duration compactly, e.g. ``42s`` or ``3m05s``."""
    total = int(seconds)
    if total < SECONDS_PER_MINUTE:
        return f"{total}s"
    return f"{total // SECONDS_PER_MINUTE}m{total % SECONDS_PER_MINUTE:02d}s"


def bar(fraction: float) -> str:
    """Return a fixed-width ``#``/``-`` bar for ``fraction`` clamped to [0, 1]."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(fraction * PROGRESS_BAR_WIDTH)
    return "#" * filled + "-" * (PROGRESS_BAR_WIDTH - filled)


def write_live(text: str) -> None:
    """Overwrite the current stderr line with ``text`` (only when stderr is a TTY)."""
    if sys.stderr.isatty():
        sys.stderr.write("\r\033[K" + text)  # \r + clear-to-end-of-line
        sys.stderr.flush()


def end_live() -> None:
    """End a live progress line with a newline (only when stderr is a TTY)."""
    if sys.stderr.isatty():
        sys.stderr.write("\n")
        sys.stderr.flush()
