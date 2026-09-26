"""The exit codes alfenctl returns.

A script can tell the three general outcomes apart: 0 means it did what was
asked, 130 is the shell's own convention for Ctrl+C (128 + SIGINT), and 1 is
everything else -- no station, no route to it, a value the charger refused.
There is deliberately no code per failure kind; the message on stderr says
which.

Those three, and the two firmware weights that mean the same thing in every
program of this shape, come from :mod:`devicectl.cli.exits`; they are
re-exported here so a caller has one place to look rather than two.  The
firmware upgrade adds two more of its own.  It is the one command a script
is likely to run unattended across a fleet, where "this image is wrong for
this charger" and "the charger never came back" call for different
reactions.
"""

from __future__ import annotations

from devicectl.cli.exits import (
    EXIT_ERROR,
    EXIT_INCOMPATIBLE,
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_UPDATE_FAILED,
)

# --- alfenctl firmware ---------------------------------------------------------------------

EXIT_UPLOAD_IN_PROGRESS = 3  # another upload is already running on the charger
EXIT_NO_FIRMWARE = 5  # no image named and none could be offered from the server

__all__ = [
    "EXIT_ERROR",
    "EXIT_INCOMPATIBLE",
    "EXIT_INTERRUPTED",
    "EXIT_NO_FIRMWARE",
    "EXIT_OK",
    "EXIT_UPDATE_FAILED",
    "EXIT_UPLOAD_IN_PROGRESS",
]
