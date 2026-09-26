"""``alfenctl loadbalancing`` -- how a station shares its supply.

The app's largest configuration panel, as one command.  Everything here is a
property write, so everything here is also reachable with ``set``; what this
adds is the grouping, the names for the numbers, and the two refusals the
charger will not make for itself -- a mode bit written without reading the
other one first, and a setting switched on that the licence does not cover.
"""

from __future__ import annotations

import argparse
import sys

from devicectl import fields
from devicectl.cli.command import Command

from alfenctl import loadbalancing
from alfenctl.charger import AlfenCharger
from alfenctl.cli.exits import EXIT_OK
from alfenctl.cli.output import print_rows


def _report_warnings(state: loadbalancing.LoadBalancing) -> None:
    """Print what the charger accepted but will not act on as it looks."""
    for caveat in state.warnings():
        print(f"warning: {caveat}", file=sys.stderr)


def cmd_loadbalancing(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show or set the load-balancing and solar-charging settings."""
    if args.action == "show":
        state = loadbalancing.read(charger)
        print_rows("Load balancing", state.rows())
        _report_warnings(state)
        return EXIT_OK

    boost: dict[int, bool] = {}
    if args.solar_boost is not None:
        on = args.solar_boost == "on"
        sockets = [args.socket] if args.socket else sorted(loadbalancing.SOLAR_BOOST)
        boost = {number: on for number in sockets}
    settings = fields.from_namespace(loadbalancing.FIELDS, args)
    if boost:
        settings["solar_boost"] = boost
    state = loadbalancing.apply(charger, settings)
    print_rows("Load balancing", state.rows())
    _report_warnings(state)
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "loadbalancing",
        help="show or set load balancing and solar charging",
        aliases=["lb"],
        description="Show or set what the app's Load balancing panel writes: "
        "the static/active mode bits (0x2064_0), the smart meter that feeds "
        "active balancing (0x5217_0, 0x2067_0, 0x2068_0), the phase settings "
        "(0x2069_0, 0x2185_0, 0x2189_0) and solar charging (0x3280_*). "
        "With no ACTION, shows them.",
    )
    lsub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    lsub.add_parser("show", help="show the load-balancing settings", parents=[common])
    lc = lsub.add_parser("set", help="change one or more settings", parents=[common])
    fields.add_arguments(loadbalancing.FIELDS, lc)
    onoff = ("on", "off")
    lc.add_argument(
        "--solar-boost",
        choices=onoff,
        help="charge this session anyway, whatever the roof is making",
    )
    lc.add_argument(
        "--socket",
        type=int,
        metavar="N",
        choices=sorted(loadbalancing.SOLAR_BOOST),
        help="only this socket, for --solar-boost (default: every socket)",
    )


COMMANDS: dict[str, Command] = {
    "loadbalancing": Command(
        cmd_loadbalancing, default_action="show", fans_out=("show",)
    ),
    "lb": Command(cmd_loadbalancing, default_action="show", fans_out=("show",)),
}
