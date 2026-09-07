"""Acts on the charger itself: its clock, its sensors, and starting over.

``erase`` and ``calibrate`` change something a reboot will not undo, so
both say what they are about to do and both take a confirmation.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from datetime import datetime, timezone

from alfenctl import clock, tilt
from alfenctl.charger import AlfenCharger
from alfenctl.upgrade import DEFAULT_REBOOT_TIMEOUT_S, REBOOT_SETTLE_S

from alfenctl.cli.command import Command, Need
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import CLOCK_FORMAT, confirm, print_rows, print_table
from alfenctl.cli.report import wait_for_reboot


def cmd_time(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show the charger's clock, or set it from this computer."""
    state = clock.read(charger)
    # The middle of the read's round trip, which is what the reading is
    # compared against -- see :attr:`alfenctl.clock.Clock.measured_at`.
    now = state.measured_at or datetime.now(timezone.utc)
    if args.action == "sync":
        was = clock.format_drift(state.drift())
        info = charger.basic_info()
        sent = clock.sync(charger, is_ahp=info.family == "AHP")
        print(
            f"{info.object_id}'s clock set to {sent.strftime(CLOCK_FORMAT)} UTC "
            f"(it was {was})."
        )
        return EXIT_OK

    drift = state.drift()
    rows: list[tuple[str, str]] = [
        (
            "Charger (UTC)",
            state.utc.strftime(CLOCK_FORMAT) if state.utc else "<not reported>",
        ),
        ("This computer", now.strftime(CLOCK_FORMAT)),
        ("Difference", clock.format_drift(drift)),
    ]
    rows.append(("Time zone", clock.format_zone(state)))
    if state.local is not None:
        rows.append(("Charger local", state.local.strftime(CLOCK_FORMAT)))
    print_rows("Charger clock", rows)
    if drift is None or abs(drift.total_seconds()) >= clock.DRIFT_NOISE_S:
        print("\nSet it from this computer with: alfenctl time sync")
    return EXIT_OK


def cmd_calibrate(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Calibrate the tilt sensor: store where the charger stands as upright."""
    state = tilt.read(charger)
    print("Tilt sensor:\n")
    stored = [
        "<none stored>" if setpoint is None else str(setpoint)
        for setpoint in state.setpoints
    ]
    width = max(len(text) for text in stored)
    for axis, value, upright in zip(tilt.AXES, state.values, stored):
        print(f"  {axis}   reading {value:>6}   upright {upright:>{width}}")
    if state.calibrated:
        print("\nThe charger already treats its current position as upright.")
        return EXIT_OK
    if not args.yes:
        print(
            "\nCalibrating stores the reading above as 'upright', so the "
            "charger\nmust already stand in its final, level position.",
            file=sys.stderr,
        )
        if not confirm("Store this position as upright?"):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    tilt.calibrate(charger, state)
    print("\nTilt sensor calibrated: this position is now upright.")
    return EXIT_OK


def cmd_reboot(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Restart the charger, and (unless --no-wait) wait for it to come back."""
    import time

    info = charger.basic_info()
    if not args.yes:
        print(
            "Rebooting interrupts any charging session in progress.",
            file=sys.stderr,
        )
        if not confirm(f"Reboot {info.object_id}?"):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    # The app lets recent writes settle before it pulls the rug.
    time.sleep(REBOOT_SETTLE_S)
    charger.reboot(is_ahp=info.family == "AHP")
    print(f"Reboot sent to {info.object_id}.")
    if args.no_wait:
        return EXIT_OK
    if not wait_for_reboot(charger, deadline_s=args.timeout, debug=args.debug):
        print(
            "The charger did not come back before the timeout; it may still "
            "be starting.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    return EXIT_OK


# What the console can do, as far as any of the three reverse-engineered
# sources record it.  Three columns, because the sources disagree about how
# much they know: the vendor's own label for the action, the string that
# actually goes over the wire when a source shows one being sent, and the
# alfenctl command that does the same thing through a documented endpoint.
#
# The labels are My Eve's (i18n_en.json, ``ChargingStationCommand.*``, kept
# in research/android/android-findings.md); the app ships names for nineteen
# commands but never the strings behind them, so most of the middle column
# is blank and stays that way until someone reads one off a charger's log.
# The strings that are filled in come from ICULanDevice (reboot, txerase,
# date, eepromx erase config, forcefirmwarepermanent — see
# research/windows/windows-findings.md) and, for `cansync off`, from a real
# NG910 charger log: "taskCommandLine: Executing: system(cansync off)".
# The list is not exhaustive: the console takes anything, and `cansync off`
# was never in any app.
CONSOLE_COMMANDS: tuple[tuple[str, str, str], ...] = (
    ("Erase Config", "eepromx erase config", "erase settings"),
    ("Erase Transactions", "txerase", "erase transactions"),
    ("Erase Log Lines", "", ""),
    ("Erase White List", "", "tags clear"),
    ("Erase Local List", "", ""),
    ("Erase Charging Profiles", "", "charging-profiles clear"),
    ("Erase Display Memory", "", ""),
    ("Dump White List", "", "tags list"),
    ("Dump Local List", "", ""),
    ("Show SCN Info", "", "scn status"),
    ("Show Connected Meter Types", "", "meter-test"),
    ("Show Flash Memory Info", "", ""),
    ("Dump Flash Memory (Caution!)", "", ""),
    ("Force Firmware Permanent", "forcefirmwarepermanent", ""),
    ("Restart Modem (if applicable)", "", ""),
    ("Run All Tests", "", ""),
    ("Tamper detection On", "", ""),
    ("Tamper detection Off", "", ""),
    ("Show Debug On Display", "", ""),
    ("Restart the station", "reboot", "reboot"),
    ("Set the clock", "date <yyyy-mm-dd hh:mm:ss>", "time sync"),
    ("Stop the CAN clock sync", "cansync off", ""),
)


# Why two thirds of the table above has no command in it.  Said wherever
# the table is shown -- the terminal prints it under `alfenctl cmd --list`
# and the web UI carries it into its own dialog (`GET /api/console`) --
# because a table two-thirds full of "unknown" reads as a table
# two-thirds broken until somebody says why.
CONSOLE_UNKNOWN_NOTE = (
    "The vendor apps name these commands but mostly do not record the string "
    "that goes over the wire, so a blank console command means unknown, not "
    "unavailable. The console accepts anything and validates nothing; prefer "
    "the alfenctl command where there is one."
)


def _list_console_commands() -> int:
    """Print what the console is known to do, and how much of it is known."""
    print_table(
        ["WHAT IT DOES", "CONSOLE COMMAND", "ALFENCTL"],
        [[what, wire, own] for what, wire, own in CONSOLE_COMMANDS],
    )
    print("\n" + textwrap.fill(CONSOLE_UNKNOWN_NOTE, 78), file=sys.stderr)
    return EXIT_OK


def cmd_cmd(charger: AlfenCharger | None, args: argparse.Namespace) -> int:
    """Send a console command to the charger (the app's Command Window)."""
    if args.action == "list":
        return _list_console_commands()
    command = " ".join(args.words).strip()
    if not command:
        print(
            "error: give a command to send, or --list to see what the "
            "console is known to do",
            file=sys.stderr,
        )
        return EXIT_ERROR
    assert charger is not None  # anything but --list needs a session
    info = charger.basic_info()
    if not args.yes:
        print(
            "The charger's command console is unvalidated: a wrong command "
            "can\ndisrupt charging or the configuration. `alfenctl cmd --list` "
            "shows what\nthe vendor apps are known to send.",
            file=sys.stderr,
        )
        if not confirm(f"Send {command!r} to {info.object_id}?"):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    charger.send_command(command)
    # The charger acknowledges the transfer, not the outcome: it reports what
    # it actually did on its own event log.
    print("Sent. The charger reports the result in its log ('alfenctl log').")
    return EXIT_OK


# What each `erase` target does, and the warning it carries.
ERASE_TARGETS = {
    "settings": (
        "the stored configuration (the charger returns to factory defaults, "
        "including its network settings -- you may lose contact with it)"
    ),
    "personal-data": (
        "personal data: RFID tags, transactions and logs (the app's "
        "'clear personal data')"
    ),
    "transactions": (
        "the transaction database, including sessions not yet reported to the "
        "backoffice"
    ),
}


def cmd_erase(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Erase settings, personal data, or the transaction database."""
    info = charger.basic_info()
    is_ahp = info.family == "AHP"
    if not args.yes:
        print(f"This erases {ERASE_TARGETS[args.target]}.", file=sys.stderr)
        print("It cannot be undone.", file=sys.stderr)
        if not confirm(f"Erase {args.target} on {info.object_id}?"):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    if args.target == "settings":
        charger.clear_settings(is_ahp=is_ahp)
        print("Settings erased; reboot the charger to start on the defaults.")
    elif args.target == "personal-data":
        charger.clear_personal_data()
        print("Personal data erased.")
    else:
        charger.erase_transactions(is_ahp=is_ahp)
        print("Transaction database erased.")
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "time",
        help="show the charger's clock, or set it from this computer",
        description="Show the charger's clock, or set it from this computer. "
        "With no ACTION, shows it.",
    )
    # As with `tags`/`password`, the connection options go on each action.
    tsub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    tsub.add_parser(
        "show", help="show the charger's clock and time zone", parents=[common]
    )
    tsub.add_parser(
        "sync",
        help="set the charger's clock to this computer's (UTC)",
        parents=[common],
    )

    sp = sub.add_parser(
        "calibrate",
        help="calibrate an on-board sensor",
        description="Calibrate an on-board sensor. This command has no "
        "default ACTION: a calibration should be a deliberate act.",
    )
    calsub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    cb = calsub.add_parser(
        "tilt",
        help="store the charger's current position as upright (it must "
        "already be installed and level)",
        parents=[common],
    )
    cb.add_argument("-y", "--yes", action="store_true", help="do not prompt")

    sp = sub.add_parser("reboot", help="restart the charger", parents=[common])
    sp.add_argument(
        "--no-wait", action="store_true", help="send the reboot and return at once"
    )
    sp.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_REBOOT_TIMEOUT_S,
        metavar="S",
        help=f"seconds to wait for it to come back (default "
        f"{DEFAULT_REBOOT_TIMEOUT_S:.0f})",
    )
    sp.add_argument("-y", "--yes", action="store_true", help="do not prompt")

    sp = sub.add_parser(
        "cmd",
        help="send a console command (the app's Command Window)",
        parents=[common],
    )
    sp.add_argument("words", nargs="*", metavar="WORD", help="the command to send")
    # store_const into `action` rather than a flag of its own, so the
    # dispatch table can say this one needs no charger at all.
    sp.add_argument(
        "--list",
        action="store_const",
        const="list",
        dest="action",
        help="print what the console is known to do, and send nothing",
    )
    sp.add_argument("-y", "--yes", action="store_true", help="do not prompt")

    sp = sub.add_parser(
        "erase", help="erase settings, personal data or transactions", parents=[common]
    )
    sp.add_argument(
        "target",
        choices=sorted(ERASE_TARGETS),
        help="what to erase",
    )
    sp.add_argument("-y", "--yes", action="store_true", help="do not prompt")


COMMANDS: dict[str, Command] = {
    "time": Command(cmd_time),
    "calibrate": Command(cmd_calibrate),
    "reboot": Command(cmd_reboot),
    "cmd": Command(cmd_cmd, per_action={"list": Need.NOTHING}),
    "erase": Command(cmd_erase),
}
