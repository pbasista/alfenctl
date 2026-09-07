"""The external energy meter: its register map, and the profiles that use it.

A charger that load-balances reads an external meter over Modbus, and a
meter the firmware does not already know needs its registers described.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from alfenctl import charging_profiles, meter_map
from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import confirm, print_table

# Firmware that does not implement /api/chargingprofiles answers this.
HTTP_NOT_FOUND = 404


def _print_meter_map(regmap: meter_map.RegisterMap) -> None:
    """Print a register map as a table."""
    print_table(
        ["MEASURAND", "REGISTER", "READ AS", "SCALE"],
        [
            [e.measurand, f"0x{e.register:04X}", e.data_type, e.factor]
            for e in regmap.entries
        ],
    )


def cmd_meter_map(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show, save, or apply the custom Modbus meter register map."""
    if args.action == "apply":
        return _apply_meter_map(charger, args)
    current = meter_map.read(charger)

    if args.action == "save":
        text = meter_map.to_json(current, name=f"{charger.station.ip} custom map")
        Path(args.file).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {len(current.entries)} entries to {args.file}")
        return EXIT_OK

    if not current.entries:
        print(
            "No custom register map is installed; the charger is reading a "
            "meter it knows,\nor none at all. Install one with: alfenctl "
            "meter-map apply <file.json>"
        )
        return EXIT_OK
    print(
        f"Custom Modbus register map ({len(current.entries)} of "
        f"{current.capacity} slots used):\n"
    )
    _print_meter_map(current)
    return EXIT_OK


def _apply_meter_map(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Apply a register map from one of Alfen's JSON files."""
    try:
        text = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {args.file}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    wanted = meter_map.parse_json(text)
    current = meter_map.read(charger)
    return write_meter_map(charger, wanted, current, args)


def write_meter_map(
    charger: AlfenCharger,
    wanted: meter_map.RegisterMap,
    current: meter_map.RegisterMap,
    args: argparse.Namespace,
) -> int:
    """Preview and (unless --dry-run) write a register map."""
    label = wanted.name or "the register map"
    print(f"Applying {label} to the smart-meter register map:\n")
    _print_meter_map(wanted)
    if current.entries:
        print(f"\nThis replaces the {len(current.entries)} entries now installed.")
    if args.dry_run:
        print("\nDry run: nothing was written.")
        return EXIT_OK
    if not args.yes:
        if not confirm("\nWrite this register map to the charger?"):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    meter_map.apply(charger, wanted, capacity=current.capacity or len(wanted.entries))
    print("Register map written.")
    print("Check the readings with: alfenctl meter-test")
    return EXIT_OK


def cmd_charging_profiles(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """List, show, clear, or install OCPP smart-charging profiles."""
    action = args.action
    try:
        if action == "install-uk":
            charger.add_charging_profile(charging_profiles.uk_default_profile())
            print(
                "UK Smart Charging default profile installed: charging is "
                "blocked 08:00-11:00 and 16:00-22:00 on weekdays, allowed "
                "the rest of the time."
            )
            return EXIT_OK
        if action == "clear":
            target = (
                args.profile_id
                if args.profile_id is not None
                else charging_profiles.CLEAR_ALL
            )
            charger.clear_charging_profile(target)
            print(f"Cleared charging profile {target}.")
            return EXIT_OK
        if action == "show":
            body = charger.fetch_charging_profile(args.profile_id).text
            profiles = charging_profiles.parse_profiles(body)
            if not profiles:
                print(f"No charging profile {args.profile_id}.", file=sys.stderr)
                return EXIT_ERROR
            if args.json:
                print(json.dumps([p.raw for p in profiles], indent=2))
                return EXIT_OK
            for p in profiles:
                print(
                    f"Profile {p.profile_id}  connector {p.connector_id}  "
                    f"{p.kind}  {p.purpose}  stack {p.stack_level}  "
                    f"unit {p.charging_rate_unit}"
                )
                if p.start_schedule:
                    print(f"  starts {p.start_schedule}")
                for period in p.periods:
                    hh, mm = divmod(period.start_period_s // 60, 60)
                    dd, hh = divmod(hh, 24)
                    print(
                        f"  +{dd}d {hh:02d}:{mm:02d}  limit {period.limit_a:g} "
                        f"{p.charging_rate_unit}"
                    )
            return EXIT_OK
        # list
        body = charger.fetch_charging_profile_ids().text
        ids = charging_profiles.parse_ids(body)
        if args.json:
            print(json.dumps(ids))
            return EXIT_OK
        if not ids:
            print("No charging profiles installed.")
            return EXIT_OK
        for pid in ids:
            tag = (
                " (UK Smart Charging default)"
                if pid == charging_profiles.UK_SMART_CHARGING_ID
                else ""
            )
            print(f"  {pid}{tag}")
        print(
            f"\n{len(ids)} profile(s). Show one with: alfenctl charging-profiles show <id>"
        )
        return EXIT_OK
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == HTTP_NOT_FOUND:
            print(
                "This charger's firmware does not support charging profiles.",
                file=sys.stderr,
            )
            return EXIT_ERROR
        raise


def cmd_direct_start(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Let a socket start charging despite an installed schedule."""
    state = charging_profiles.read_direct_start(charger)
    if not state.overrides and state.random_delay_s is None:
        print(
            "This charger's firmware does not carry the charging-profile "
            "override (0x3278_1).",
            file=sys.stderr,
        )
        return EXIT_ERROR

    if args.action == "show":
        rows = state.rows()
        print_table(["SETTING", "VALUE"], [[a, b] for a, b in rows])
        if not _profile_installed(charger):
            print(
                "\nNo charging profile is installed, so the override has "
                "nothing to override.",
                file=sys.stderr,
            )
        return EXIT_OK

    direct = args.action == "on"
    if direct and not _profile_installed(charger):
        # Writing it blindly is what leaves someone convinced the setting is
        # broken: with no profile there is nothing for it to do.
        print(
            "warning: no charging profile is installed, so direct start "
            "changes nothing until one is (alfenctl charging-profiles install-uk)",
            file=sys.stderr,
        )
    numbers = [args.socket] if args.socket else sorted(state.overrides) or [1]
    after = charging_profiles.set_direct_start(
        charger,
        sockets=dict.fromkeys(numbers, direct),
        random_delay_s=args.random_delay,
        state=state,
    )
    print_table(["SETTING", "VALUE"], [[a, b] for a, b in after.rows()])
    return EXIT_OK


def _profile_installed(charger: AlfenCharger) -> bool:
    """Whether the charger holds any profile for the override to override."""
    try:
        return bool(
            charging_profiles.parse_ids(charger.fetch_charging_profile_ids().text)
        )
    except httpx.HTTPStatusError:
        return False


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "meter-map",
        help="custom Modbus register map for an external energy meter",
        description="Show, save or apply the register map the charger uses "
        "to read a smart meter it does not know by name. With no ACTION, "
        "shows the installed map.",
    )
    mmsub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    mm = mmsub.add_parser(
        "show", help="show the map the charger holds", parents=[common]
    )
    mm = mmsub.add_parser(
        "save", help="write the charger's map to a JSON file", parents=[common]
    )
    mm.add_argument("file", help="file to write")
    mm = mmsub.add_parser(
        "apply", help="write a map from a JSON file", parents=[common]
    )
    mm.add_argument("file", help="register-map JSON (Alfen's own preset format)")
    mm.add_argument(
        "--dry-run", action="store_true", help="preview the map, write nothing"
    )
    mm.add_argument("-y", "--yes", action="store_true", help="do not prompt")

    sp = sub.add_parser(
        "charging-profiles",
        help="list, show, clear, or install OCPP smart-charging profiles",
        aliases=["charging-profile"],
        description="List, show, clear, or install OCPP smart-charging "
        "profiles. With no ACTION, lists the installed profile ids.",
    )
    # As with `tags`/`password`, the connection options go on each action.
    cpsub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    cp = cpsub.add_parser("list", help="list installed profile ids", parents=[common])
    cp.add_argument("--json", action="store_true", help="JSON instead of a table")
    cp = cpsub.add_parser("show", help="show one profile's schedule", parents=[common])
    cp.add_argument("profile_id", type=int, help="the profile id (from 'list')")
    cp.add_argument("--json", action="store_true", help="the charger's raw JSON")
    cp = cpsub.add_parser(
        "clear", help="remove one profile, or all of them", parents=[common]
    )
    cp.add_argument(
        "profile_id",
        nargs="?",
        type=int,
        help="the profile id to remove (default: every profile)",
    )
    cp = cpsub.add_parser(
        "install-uk",
        help="install the UK Smart Charging default weekly schedule",
        parents=[common],
    )

    sp = sub.add_parser(
        "direct-start",
        help="charge now despite an installed charging profile",
        description="Show or set the per-socket override of an installed "
        "charging profile (0x3278_1, 0x3278_2) -- the app's `Direct start on "
        "socket N`, which lets a driver charge during a window the profile "
        "blocks. Also carries the randomised start delay (0x21B9_0) the UK "
        "regulation asks for. With no ACTION, shows them.",
    )
    dsub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    for name, helptext in (
        ("show", "show the override and the random delay"),
        ("on", "override the profile: start charging now"),
        ("off", "follow the installed profile again"),
    ):
        dc = dsub.add_parser(name, help=helptext, parents=[common])
        if name == "show":
            continue
        dc.add_argument(
            "--socket",
            type=int,
            metavar="N",
            choices=sorted(charging_profiles.SOCKET_OVERRIDE),
            help="only this socket (default: every socket the charger reports)",
        )
        dc.add_argument(
            "--random-delay",
            type=int,
            metavar="SECONDS",
            help="the randomised start delay, 0-"
            f"{charging_profiles.MAX_RANDOM_DELAY_S} "
            f"(below {charging_profiles.COMPLIANT_RANDOM_DELAY_S} is not "
            "UK-compliant)",
        )


COMMANDS: dict[str, Command] = {
    "meter-map": Command(cmd_meter_map),
    "charging-profiles": Command(cmd_charging_profiles),
    "charging-profile": Command(cmd_charging_profiles),
    "direct-start": Command(cmd_direct_start),
}
