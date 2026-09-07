"""An upgrade's progress, turned into events for the browser.

A firmware job is one bar in the UI, but the work behind it comes in three
parts of very different length: an optional download from Alfen's server,
the upload to the charger, and the install the charger does on its own.
Each gets a slice of the bar, so it keeps moving instead of sitting at
100% for three minutes.  The slices are guesses about duration and nothing
depends on them being right.
"""

from __future__ import annotations

from alfenctl.report import Reporter, Wait
from alfenctl.web.session import Job

# Where a download from Alfen's server ends, when the job starts with one.
DOWNLOAD_SHARE_OF_JOB = 0.15
# What we assume an upload costs, to keep the job's progress bar moving
# through the install phase rather than sitting at 100%.
UPLOAD_SHARE_OF_JOB = 0.6
# Where the install phase ends, leaving the last sliver for the commit.
INSTALL_SHARE_OF_JOB = 0.95


class JobReporter(Reporter):
    """Reports an upgrade's progress onto a :class:`~alfenctl.web.session.Job`.

    ``start`` is where the upload begins on the bar -- 0 for an uploaded
    file, :data:`DOWNLOAD_SHARE_OF_JOB` when the image had to be fetched
    first.  Warnings are kept as well as shown, because the job's result is
    what the browser still has to look at once the run is over.
    """

    def __init__(self, job: Job, *, start: float = 0.0) -> None:
        """Report onto ``job``, with the upload phase starting at ``start``."""
        self.job = job
        self.start = start
        self.warnings: list[str] = []

    def step(self, message: str) -> None:
        """Show the new phase as the job's message."""
        self.job.report(message=message, force=True)

    def detail(self, message: str) -> None:
        """Show a detail as the job's message; the browser has one line."""
        self.job.report(message=message, force=True)

    def warn(self, message: str) -> None:
        """Show a warning and keep it for the job's result."""
        self.warnings.append(message)
        self.job.report(message=f"Warning: {message}", force=True)

    def sending(self, sent: int, total: int, elapsed_s: float) -> None:
        """Move the bar across the upload's slice."""
        span = UPLOAD_SHARE_OF_JOB - self.start
        self.job.report(self.start + span * (sent / total if total else 1.0))

    def waiting(self, wait: Wait) -> None:
        """Move the bar across the install's slice, by elapsed time."""
        self.job.report(self._install_progress(wait))

    def polled(self, wait: Wait) -> None:
        """Move the bar, and say what the charger last answered."""
        self.job.report(self._install_progress(wait), wait.label)

    def _install_progress(self, wait: Wait) -> float:
        """Map elapsed install time onto the install slice of the bar."""
        span = INSTALL_SHARE_OF_JOB - UPLOAD_SHARE_OF_JOB
        done = min(wait.elapsed_s / wait.deadline_s, 1.0) if wait.deadline_s else 1.0
        return UPLOAD_SHARE_OF_JOB + span * done
