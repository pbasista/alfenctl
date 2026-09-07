"""Where a long operation says what it is doing.

A firmware upgrade takes minutes and has plenty to say meanwhile: which
step it is on, how far the upload has got, what the charger answered while
it rebooted.  The CLI draws that on a terminal and the web UI pushes it to
an event stream, so :mod:`alfenctl.upgrade` says it to a *reporter* rather
than printing it -- which is what lets both front ends drive the same
upgrade code.

:data:`SILENT` is the default everywhere: it discards the lot, which is
what a test or a library caller wants.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Wait:
    """How a wait for the charger is going, for whoever draws the progress.

    ``typical_s`` is how long this normally takes and ``deadline_s`` when we
    give up; showing the two apart is what stops a two-minute reboot looking
    like a fifteen-minute hang.
    """

    elapsed_s: float
    deadline_s: float
    typical_s: float
    label: str  # what the charger last answered, in words
    poll: int  # how many times we have asked
    next_poll_in_s: float | None  # None while a request is in flight


class Reporter:
    """Somewhere to report progress to.  This one reports it nowhere.

    Subclass and override what you can show; every method is optional and
    none of them may raise -- a reporter is called from the middle of an
    upgrade, and a broken progress bar must not fail one.
    """

    def step(self, message: str) -> None:
        """Announce a new phase of the operation."""

    def detail(self, message: str) -> None:
        """Show a detail from inside the current phase."""

    def warn(self, message: str) -> None:
        """Flag something that went wrong but does not stop the operation."""

    def sending(self, sent: int, total: int, elapsed_s: float) -> None:
        """Note that ``sent`` of ``total`` bytes of the current upload have gone out."""

    def waiting(self, wait: Wait) -> None:
        """Redraw whatever shows a wait in progress; called about once a second."""

    def polled(self, wait: Wait) -> None:
        """Record that a poll came back; ``wait.label`` says what it meant."""


SILENT = Reporter()
