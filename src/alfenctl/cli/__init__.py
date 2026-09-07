"""The command-line interface.

The package is one module per concern, and one module per group of
commands:

* :mod:`alfenctl.cli.main` -- parse, open what the command needs, run it;
* :mod:`alfenctl.cli.parser` -- the root parser and the shared options;
* :mod:`alfenctl.cli.command` -- what a subcommand is (:class:`Command`);
* :mod:`alfenctl.cli.commands` -- the command groups, and the table that
  maps a typed word to the function that runs it;
* :mod:`alfenctl.cli.target` -- which charger, and as whom;
* :mod:`alfenctl.cli.output` -- tables, shared formats, the one prompt;
* :mod:`alfenctl.cli.report` -- progress on a terminal;
* :mod:`alfenctl.cli.exits` -- the process exit codes.

To add a command: write the handler in the right module of
:mod:`alfenctl.cli.commands`, describe it in that module's
``add_parsers``, and name it in that module's ``COMMANDS``.

Messages on stderr open with ``error:`` when the command failed and
``warning:`` when it carried on regardless -- the same two words argparse
prints, so a script can grep for one prefix instead of several.  A
declined prompt says ``Aborted.``, and a command that simply found
nothing says so in a sentence; neither is a malfunction.
"""

from alfenctl.cli.commands.access import DEFAULT_TEMP_PASSWORD_HOURS
from alfenctl.cli.commands.status import DEFAULT_WATCH_INTERVAL_S
from alfenctl.cli.exits import (
    EXIT_ERROR,
    EXIT_INCOMPATIBLE,
    EXIT_INTERRUPTED,
    EXIT_NO_FIRMWARE,
    EXIT_OK,
    EXIT_UPDATE_FAILED,
    EXIT_UPLOAD_IN_PROGRESS,
)
from alfenctl.cli.main import main
from alfenctl.cli.parser import DEFAULT_ACTIONS, build_parser, insert_default_action

__all__ = [
    "DEFAULT_ACTIONS",
    "DEFAULT_TEMP_PASSWORD_HOURS",
    "DEFAULT_WATCH_INTERVAL_S",
    "EXIT_ERROR",
    "EXIT_INCOMPATIBLE",
    "EXIT_INTERRUPTED",
    "EXIT_NO_FIRMWARE",
    "EXIT_OK",
    "EXIT_UPDATE_FAILED",
    "EXIT_UPLOAD_IN_PROGRESS",
    "build_parser",
    "insert_default_action",
    "main",
]
