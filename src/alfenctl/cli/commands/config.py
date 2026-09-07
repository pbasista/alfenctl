"""``alfenctl config`` -- where the settings file is, and what is in it.

A charger is reached by typing an address and a password, or by writing
them down once.  These three commands are the "write them down once" half:
where the file goes, how to start one, and what alfenctl actually read out
of it.  None of them touches a charger.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alfenctl.charger import AlfenCharger
from alfenctl.config import EXAMPLE_CONFIG, default_config_path, load_config

from alfenctl.cli.command import Command, Need
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import confirm, print_table

# Stand-in for a password, so `config show` can be pasted into a bug report.
REDACTED = "<set>"


def cmd_config(charger: AlfenCharger | None, args: argparse.Namespace) -> int:
    """Show, locate or create the configuration file (no charger involved)."""
    path = Path(args.config).expanduser() if args.config else default_config_path()
    if args.action == "path":
        print(path)
        return EXIT_OK
    if args.action == "init":
        return _init(path, yes=args.yes)
    return _show(path)


def _init(path: Path, *, yes: bool) -> int:
    """Write a commented starter file, and say what to do with it."""
    if path.exists() and not yes and not confirm(f"'{path}' already exists. Replace?"):
        print("Aborted.", file=sys.stderr)
        return EXIT_ERROR
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    print(
        f"Wrote {path}.\n"
        "Every line is commented out; uncomment the ones you need. "
        "Check the result with: alfenctl config show"
    )
    return EXIT_OK


def _show(path: Path) -> int:
    """Print what alfenctl read, with the passwords left out."""
    if not path.is_file():
        print(
            f"No configuration file at {path}.\n"
            "Create one with: alfenctl config init\n"
            "(alfenctl works without one; --station/--host and -u/-p then "
            "carry the same information on every command.)",
            file=sys.stderr,
        )
        return EXIT_ERROR
    config = load_config(path)
    print(f"Configuration: {path}\n")
    rows = [
        ["username", config.username or "-"],
        ["password", REDACTED if config.password else "-"],
        ["host", config.host or "-"],
        ["firmware site", config.firmware.location],
    ]
    print_table(["SETTING", "VALUE"], rows)
    if not config.stations:
        print("\nNo [stations.<name>] tables; --station takes an Object ID or IP.")
        return EXIT_OK
    print(f"\n{len(config.stations)} station(s):\n")
    print_table(
        ["NAME", "HOST", "PROTO", "USERNAME", "PASSWORD"],
        [
            [
                station.name,
                f"{station.host}:{station.port}" if station.port else station.host,
                "http" if station.http else "https",
                station.username or "-",
                REDACTED if station.password else "-",
            ]
            for station in config.stations.values()
        ],
    )
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "config",
        help="show, locate or create the alfen.toml settings file",
        parents=[common],
    )
    actions = sp.add_subparsers(dest="action", metavar="ACTION")
    actions.add_parser("show", help="show what alfenctl reads (without passwords)")
    actions.add_parser("path", help="print the path of the settings file")
    init = actions.add_parser("init", help="write a commented starter file")
    init.add_argument(
        "-y", "--yes", action="store_true", help="replace an existing file"
    )


COMMANDS: dict[str, Command] = {"config": Command(cmd_config, needs=Need.NOTHING)}
