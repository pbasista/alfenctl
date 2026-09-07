"""The exit codes alfenctl returns.

A script can tell the three general outcomes apart: 0 means it did what was
asked, 130 is the shell's own convention for Ctrl+C (128 + SIGINT), and 1 is
everything else -- no station, no route to it, a value the charger refused.
There is deliberately no code per failure kind; the message on stderr says
which.

The firmware upgrade is the exception.  It is the one command a script is
likely to run unattended across a fleet, where "this image is wrong for
this charger" and "the charger never came back" call for different
reactions, so it has four codes of its own.
"""

from __future__ import annotations

EXIT_OK = 0

EXIT_ERROR = 1  # generic failure: station not found, comms error, invalid input

EXIT_INTERRUPTED = 130  # Ctrl+C (128 + SIGINT), by shell convention

# --- alfenctl firmware ---------------------------------------------------------------------

EXIT_INCOMPATIBLE = 2  # the image failed the compatibility checks
EXIT_UPLOAD_IN_PROGRESS = 3  # another upload is already running on the charger
EXIT_UPDATE_FAILED = 4  # upload sent, but the install reached no good state
EXIT_NO_FIRMWARE = 5  # no image named and none could be offered from the server
