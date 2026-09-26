"""Building the command-line parser out of the command groups.

The root parser knows only the program's own options and the list of
groups; each group in :mod:`alfenctl.cli.commands` describes its own
subcommands.  Adding a command means editing one file, not scrolling to
the right place in a long one.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from devicectl.cli.parser import (
    default_actions,
    insert_default_action as _insert_default_action,
    insert_default_command as _insert_default_command,
)

from alfenctl.cli.commands import COMMANDS, GROUPS
from alfenctl.config import default_config_path
from alfenctl.discovery import DEFAULT_DISCOVER_TIME_S, DEFAULT_HTTPS_PORT

# What a command does when its ACTION is left out, read off the command table
# rather than listed again here: an action qualifies only if it needs no
# further input and only reads, and `password` has none on purpose, because
# every one of its actions changes something.
DEFAULT_ACTIONS = default_actions(COMMANDS)


def _version_text() -> str:
    """Return the --version string."""
    from alfenctl import __version__

    return f"alfenctl {__version__}"


def common_options() -> argparse.ArgumentParser:
    """Build the parent parser carrying the options every command shares.

    Passed as ``parents=[common]`` to each subparser, so the fifty-odd
    commands describe how to reach a charger in one place rather than
    fifty.  ``add_help=False`` because each child adds its own ``-h``.
    """
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--station",
        metavar="NAME",
        help="station name (alfen.toml), Object ID, or IP; a comma-separated "
        "list, or 'all' for every station in alfen.toml, runs a read over "
        "each of them",
    )
    p.add_argument("--host", help="talk to a charger at this IP directly")
    # These two default to None, not to their real defaults, so that
    # resolve_target can tell "not given" from "given the usual value".
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"charger port (default {DEFAULT_HTTPS_PORT})",
    )
    p.add_argument(
        "--http",
        action="store_true",
        default=None,
        help="use the old HTTP protocol (pre-5.0)",
    )
    p.add_argument("-u", "--username", help="charger login username")
    p.add_argument("-p", "--password", help="charger login password")
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"settings file (default: {default_config_path()})",
    )
    p.add_argument(
        "--discover-time",
        type=float,
        default=DEFAULT_DISCOVER_TIME_S,
        help="seconds to browse for stations (default 4)",
    )
    p.add_argument(
        "--debug", action="store_true", help="log every HTTP request/response to stderr"
    )
    return p


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    common = common_options()
    p = argparse.ArgumentParser(
        prog="alfenctl",
        description="Discover Alfen charging stations, inspect and change their "
        "properties, upgrade firmware and upload logos (a reimplementation of "
        "the basics of Alfen's ACE Service Installer).  Run with no command at "
        "all to serve the web interface, which is the usual way to use it; "
        "everything the page does is also one of the commands below.",
    )
    p.add_argument("--version", action="version", version=_version_text())
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    for group in GROUPS:
        group.add_parsers(sub, common)
    return p


def insert_default_command(argv: list[str]) -> list[str]:
    """Return ``argv`` with ``ui`` filled in when no command was typed.

    ``alfenctl`` on its own serves the web interface, because that is how
    most people use this program and a page of usage text is not what they
    came for.  Options meant for it are handed through, so ``alfenctl
    --station garage`` opens the page on that station rather than
    complaining that ``--station`` belongs to a subcommand.
    """
    return _insert_default_command(argv, "ui")


def insert_default_action(argv: list[str]) -> list[str]:
    """Return ``argv`` with a command's default ACTION filled in, if missing.

    ``alfenctl tags`` becomes ``alfenctl tags list``, and options meant for
    that default action are handed through to it (``alfenctl scn --peers``
    becomes ``alfenctl scn status --peers``), because the connection options
    live on the action parsers rather than the command itself.
    """
    return _insert_default_action(argv, DEFAULT_ACTIONS)


__all__ = [
    "DEFAULT_ACTIONS",
    "build_parser",
    "common_options",
    "insert_default_action",
    "insert_default_command",
]
