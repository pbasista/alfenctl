"""Where an upgrade's phases sit on the one bar the browser draws.

A firmware job is one bar in the UI, but the work behind it comes in three
parts of very different length: an optional download from Alfen's server,
the upload to the charger, and the install the charger does on its own.
:class:`devicectl.web.progress.JobReporter` maps a reporter's calls onto
slices of that bar; what is here is where alfenctl's slices fall.

They are guesses about duration and nothing depends on them being right --
only on the bar continuing to move rather than sitting at 100% for three
minutes while the charger installs.
"""

from __future__ import annotations

from devicectl.web.progress import JobReporter, Phases

# Where a download from Alfen's server ends, when the job starts with one.
DOWNLOAD_SHARE_OF_JOB = 0.15
# What we assume an upload costs, to keep the job's progress bar moving
# through the install phase rather than sitting at 100%.
UPLOAD_SHARE_OF_JOB = 0.6
# Where the install phase ends, leaving the last sliver for the commit.
INSTALL_SHARE_OF_JOB = 0.95

UPGRADE_PHASES = Phases(
    sending_ends=UPLOAD_SHARE_OF_JOB, waiting_ends=INSTALL_SHARE_OF_JOB
)


# A download is one transfer and nothing else, so it gets the first slice of
# the bar to itself; the upload that follows starts where it stopped.
DOWNLOAD_PHASES = Phases(sending_ends=DOWNLOAD_SHARE_OF_JOB)


def upgrade_reporter(job, *, start: float = 0.0) -> JobReporter:
    """Report an upgrade onto ``job``, with alfenctl's three phases."""
    return JobReporter(job, start=start, phases=UPGRADE_PHASES)


def download_reporter(job) -> JobReporter:
    """Report a firmware download onto the first slice of ``job``'s bar."""
    return JobReporter(job, phases=DOWNLOAD_PHASES)


__all__ = [
    "DOWNLOAD_PHASES",
    "DOWNLOAD_SHARE_OF_JOB",
    "INSTALL_SHARE_OF_JOB",
    "UPGRADE_PHASES",
    "UPLOAD_SHARE_OF_JOB",
    "JobReporter",
    "download_reporter",
    "upgrade_reporter",
]
