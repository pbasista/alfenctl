"""What the charger is doing right now: its sockets, and its meter.

Everything here is a read of live state, cheap enough to repeat -- which
is why ``status`` and ``meter-test`` can both sit in a watch loop.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any


from alfenctl import meter_test
from alfenctl import status as status_mod
from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import CLOCK_FORMAT

# `status --watch` without a number: the app's own monitoring panel polls
# once a second, but a whole category walk per reading is heavier than that.
DEFAULT_WATCH_INTERVAL_S = 2.0


def cmd_status(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show what the charger is doing right now (the app's Monitoring panel)."""
    if args.watch:
        return _watch_status(charger, args)
    return _print_status(charger, args)


def _watch_status(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Redraw the status every ``--watch`` seconds, like the app's live panel."""
    import time

    live = sys.stdout.isatty()
    while True:
        if live:
            # Home the cursor and clear what is below, so the reading stays
            # in one place instead of scrolling past.
            sys.stdout.write("\033[H\033[J")
        rc = _print_status(charger, args)
        if rc != EXIT_OK:
            return rc
        print(
            f"\n  updated {datetime.now().strftime(CLOCK_FORMAT)}, every "
            f"{args.watch:g}s -- press Ctrl+C to stop"
        )
        time.sleep(args.watch)


def _print_status(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Print one status reading."""
    info = charger.basic_info()
    snapshot = status_mod.collect(charger, info.sockets or 1)
    if args.json:
        print(json.dumps(_status_json(snapshot), indent=2))
        return EXIT_OK
    print(f"{info.object_id} ({info.model}), firmware {info.firmware}\n")
    lines = status_mod.render(snapshot)
    if not lines:
        print(
            "The charger reported none of the live state properties.",
            file=sys.stderr,
        )
        return EXIT_OK
    print("\n".join(lines))
    return EXIT_OK


def _status_json(snapshot: status_mod.Status) -> dict[str, Any]:
    """Render a status snapshot as JSON, dropping what the charger did not report."""
    doc: dict[str, Any] = {
        "sockets": [
            {
                k: v
                for k, v in (
                    ("socket", socket.number),
                    ("state", socket.main_state),
                    ("mode3", socket.mode3_state),
                    ("led", socket.led_state),
                    ("power", socket.power_state),
                    ("display", socket.device_state),
                    ("error_code", socket.error_code),
                    ("error", socket.error_text),
                    ("error_severity", socket.error_severity),
                    ("operative", socket.operative),
                )
                if v is not None
            }
            for socket in snapshot.sockets
        ]
    }
    for name, value in (
        ("station_operative", snapshot.station_operative),
        ("temperature_c", snapshot.temperature_c),
        ("max_station_current_a", snapshot.max_station_current_a),
        ("max_installation_current_a", snapshot.max_installation_current_a),
        ("active_safe_current_a", snapshot.active_safe_current_a),
        ("active_power_w", snapshot.active_power_w),
        ("energy_delivered_kwh", snapshot.energy_delivered_kwh),
        ("energy_consumed_kwh", snapshot.energy_consumed_kwh),
    ):
        if value is not None:
            doc[name] = value
    if snapshot.voltages_v:
        doc["voltages_v"] = snapshot.voltages_v
    if snapshot.currents_a:
        doc["currents_a"] = snapshot.currents_a
    return doc


def cmd_meter_test(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show the live smart-meter test readings (the app's Modbus test dialog)."""
    values = charger.properties(meter_test.CATEGORY)
    readings = meter_test.read(values)
    if args.json:
        print(
            json.dumps(
                [
                    {"label": r.label, "value": r.value, "unit": r.unit}
                    for r in readings
                ],
                indent=2,
            )
        )
        return EXIT_OK
    if all(r.value is None for r in readings):
        print(
            "No smart-meter test readings; is a Modbus TCP/RTU meter configured?",
            file=sys.stderr,
        )
        return EXIT_ERROR
    width = max(len(r.label) for r in readings)
    for r in readings:
        value = f"{r.value} {r.unit}" if r.value is not None else "-"
        print(f"  {r.label.ljust(width)}  {value}")
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "status", help="show what the charger is doing right now", parents=[common]
    )
    sp.add_argument("--json", action="store_true", help="JSON instead of a report")
    sp.add_argument(
        "--watch",
        nargs="?",
        type=float,
        const=DEFAULT_WATCH_INTERVAL_S,
        metavar="S",
        help=f"keep re-reading and redrawing every S seconds until Ctrl+C "
        f"(default {DEFAULT_WATCH_INTERVAL_S:g})",
    )

    sp = sub.add_parser(
        "meter-test",
        help="show live smart-meter (Modbus TCP/RTU) test readings",
        parents=[common],
    )
    sp.add_argument("--json", action="store_true", help="JSON instead of a table")


COMMANDS: dict[str, Command] = {
    "status": Command(cmd_status),
    "meter-test": Command(cmd_meter_test),
}
