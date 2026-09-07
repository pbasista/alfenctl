"""``alfenctl list`` and ``alfenctl info`` -- finding a charger and its identity."""

from __future__ import annotations

import argparse
import sys

from alfenctl import clock, hardware
from alfenctl.charger import AlfenCharger
from alfenctl.discovery import discover
from alfenctl.cli.command import Command, Need
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import CLOCK_FORMAT, print_table
from alfenctl.cli.commands.license import license_fields


def cmd_list(charger: AlfenCharger | None, args: argparse.Namespace) -> int:
    """List the charging stations discovered on the local network (no session)."""
    stations = discover(args.discover_time)
    if not stations:
        print(
            "No chargers found on the local network.\n"
            "  (Discovery is mDNS-based, so you must be on the same LAN as the charger.\n"
            "   You can also target one directly with --host <ip>.)",
            file=sys.stderr,
        )
        return EXIT_ERROR
    print(f"Found {len(stations)} charging station(s):\n")
    print_table(
        ["OBJECT ID", "ADDRESS", "PROTO", "HOSTNAME"],
        [
            [
                s.object_id,
                f"{s.ip}:{s.port}",
                "https" if s.https else "http",
                s.hostname,
            ]
            for s in stations
        ],
    )
    return EXIT_OK


def cmd_info(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Print a few basic details about one station."""
    from alfenctl.license import read_license

    info = charger.basic_info()
    print("Station information:\n")
    fields: list[tuple[str, object]] = [
        ("Object ID", info.object_id),
        ("Identity", info.identity),
        ("Model", info.model),
        ("Family", info.family),
        ("Firmware", info.firmware),
        ("Sockets", info.sockets),
    ]
    fields.extend(hardware.read(charger).rows())
    state = clock.read(charger)
    if state.utc is not None:
        drift = state.drift()
        note = (
            ""
            if drift is None or abs(drift.total_seconds()) < clock.DRIFT_NOISE_S
            else f"  ({clock.format_drift(drift)})"
        )
        fields.append(("Clock", f"{state.utc.strftime(CLOCK_FORMAT)} UTC{note}"))
    lic = read_license(charger)
    if (
        lic.features_raw is not None
        or info.family == "AHP"
        or lic.license_key is not None
    ):
        fields += license_fields(info, lic)
    width = max(len(label) for label, _ in fields)
    for label, value in fields:
        print(f"  {label:<{width}} : {value if value not in (None, '') else '-'}")
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sub.add_parser(
        "list",
        help="discover charging stations on the local network",
        parents=[common],
    )

    sub.add_parser(
        "info", help="show basic information about one station", parents=[common]
    )


COMMANDS: dict[str, Command] = {
    "list": Command(cmd_list, needs=Need.NOTHING),
    "info": Command(cmd_info),
}
