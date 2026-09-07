"""Building the command-line parser out of the command groups.

The root parser knows only the program's own options and the list of
groups; each group in :mod:`alfenctl.cli.commands` describes its own
subcommands.  Adding a command means editing one file, not scrolling to
the right place in a long one.
"""

from __future__ import annotations

import argparse

from pathlib import Path

from alfenctl.config import default_config_path
from alfenctl.discovery import DEFAULT_DISCOVER_TIME_S, DEFAULT_HTTPS_PORT

from alfenctl.cli.commands import GROUPS


# Commands that take an ACTION, and the action to run when none is given, so
# that `alfenctl scn` reports the membership instead of a usage error.  An
# action qualifies only if it needs no further input and only reads; `password`
# has no entry on purpose, because every one of its actions changes something.
DEFAULT_ACTIONS = {
    "brightness": "show",
    "config": "show",
    "current": "show",
    "license": "show",
    "auth": "show",
    "authorization": "show",
    "loadbalancing": "show",
    "ocpp": "show",
    "socket": "show",
    "wifi": "scan",
    "lb": "show",
    "tags": "list",
    "whitelist": "list",
    "charging-profiles": "list",
    "charging-profile": "list",
    "direct-start": "show",
    "scn": "status",
    "time": "show",
    "secret": "list",
    "meter-map": "show",
}


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
    p.add_argument("--station", help="station name (alfen.toml), Object ID, or IP")
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
        "the basics of Alfen's ACE Service Installer).",
    )
    p.add_argument("--version", action="version", version=_version_text())
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    for group in GROUPS:
        group.add_parsers(sub, common)
    return p


def insert_default_action(argv: list[str]) -> list[str]:
    """Return ``argv`` with a command's default ACTION filled in, if missing.

    ``alfenctl tags`` becomes ``alfenctl tags list``, and options meant for
    that default action are handed through to it (``alfenctl scn --peers``
    becomes ``alfenctl scn status --peers``), because the connection options
    live on the action parsers rather than the command itself.  A leading
    word is left alone, so a mistyped action still gets argparse's "invalid
    choice", and so does ``-h``, which must reach the command's own parser
    to list the actions.
    """
    if not argv or argv[0] not in DEFAULT_ACTIONS:
        return argv
    rest = argv[1:]
    if rest and (not rest[0].startswith("-") or rest[0] in ("-h", "--help")):
        return argv
    return [argv[0], DEFAULT_ACTIONS[argv[0]], *rest]


__all__ = ["DEFAULT_ACTIONS", "build_parser", "common_options", "insert_default_action"]
