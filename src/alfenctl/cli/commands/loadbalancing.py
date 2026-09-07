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

from alfenctl import loadbalancing
from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_OK
from alfenctl.cli.output import print_rows


def _report_warnings(state: loadbalancing.LoadBalancing) -> None:
    """Print what the charger accepted but will not act on as it looks."""
    for caveat in state.warnings():
        print(f"warning: {caveat}", file=sys.stderr)


def _on_off(value: str | None) -> bool | None:
    """Turn an ``on``/``off`` argument into a flag, leaving None alone."""
    return None if value is None else value == "on"


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
    state = loadbalancing.apply(
        charger,
        static=_on_off(args.static),
        active=_on_off(args.active),
        protocol=args.protocol,
        data_source=args.data_source,
        max_meter_current_a=args.max_meter_current,
        safe_current_a=args.safe_current,
        max_imbalance_a=args.max_imbalance,
        phase_rotation=args.phase_rotation,
        measurement_includes_ev=_on_off(args.includes_ev),
        phase_switching=_on_off(args.phase_switching),
        max_allowed_phases=args.max_phases,
        solar_mode=args.solar_mode,
        solar_green_share=args.green_share,
        solar_comfort_w=args.comfort_level,
        solar_boost=boost or None,
    )
    print_rows("Load balancing", state.rows())
    _report_warnings(state)
    return EXIT_OK


def _enum_help(table: dict[int, str]) -> str:
    """Render an enumeration as ``value (label)`` pairs for a help string."""
    return ", ".join(f"{value} ({label})" for value, label in sorted(table.items()))


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
    onoff = ("on", "off")
    lc.add_argument("--static", choices=onoff, help="static load balancing")
    lc.add_argument("--active", choices=onoff, help="active load balancing")
    lc.add_argument(
        "--protocol",
        type=int,
        metavar="N",
        help=f"smart meter protocol: {_enum_help(loadbalancing.PROTOCOLS)}",
    )
    lc.add_argument(
        "--data-source",
        type=int,
        metavar="N",
        help=f"what active balancing follows: {_enum_help(loadbalancing.DATA_SOURCES)}",
    )
    lc.add_argument(
        "--max-meter-current",
        type=float,
        metavar="AMPS",
        help="the grid connection's limit",
    )
    lc.add_argument(
        "--safe-current",
        type=float,
        metavar="AMPS",
        help="what to fall back to when the meter stops answering",
    )
    lc.add_argument(
        "--max-imbalance",
        type=float,
        metavar="AMPS",
        help="allowed imbalance between phases",
    )
    lc.add_argument(
        "--phase-rotation",
        choices=loadbalancing.PHASE_ROTATIONS,
        help="how the phases are wired to this station",
    )
    lc.add_argument(
        "--includes-ev",
        choices=onoff,
        help="whether the meter's reading already counts the charging car",
    )
    lc.add_argument(
        "--phase-switching", choices=onoff, help="allow 1-/3-phase switching"
    )
    lc.add_argument(
        "--max-phases",
        type=int,
        choices=loadbalancing.ALLOWED_PHASES,
        help="the most phases a session may use",
    )
    lc.add_argument(
        "--solar-mode",
        type=int,
        metavar="N",
        help=f"solar charging: {_enum_help(loadbalancing.SOLAR_MODES)}",
    )
    lc.add_argument(
        "--green-share",
        type=int,
        metavar="PERCENT",
        help="surplus share to charge from",
    )
    lc.add_argument(
        "--comfort-level",
        type=int,
        metavar="WATTS",
        help="the floor comfort mode keeps",
    )
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
    "loadbalancing": Command(cmd_loadbalancing),
    "lb": Command(cmd_loadbalancing),
}
