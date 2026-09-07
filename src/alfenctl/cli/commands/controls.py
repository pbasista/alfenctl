"""``alfenctl current``, ``brightness`` and ``socket`` -- the live dials.

All three are property writes the charger can quietly ignore or clamp, so all
three read the state back and report what actually took effect.
"""

from __future__ import annotations

import argparse
import sys

from alfenctl import controls, status
from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import confirm, print_rows


def _report_control_warnings(state: controls.Controls) -> None:
    """Print what the charger accepted but will not act on as it looks."""
    for caveat in state.warnings():
        print(f"warning: {caveat.detail}", file=sys.stderr)


def cmd_current(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show or set the charging current limits (the app's Power panel)."""
    state = controls.read(charger)
    if args.action == "show":
        print_rows("Charging current limits", controls.format_current(state))
        print()
        _report_control_warnings(state)
        print("Set a socket's limit with: alfenctl current set 10")
        return EXIT_OK

    if args.station_max:
        if args.external:
            print(
                "error: --external applies to a socket, not to the station",
                file=sys.stderr,
            )
            return EXIT_ERROR
        after = controls.apply(charger, station_max_a=args.amps, state=state)
        changed = "The station maximum"
    else:
        numbers = [args.socket] if args.socket else sorted(state.sockets)
        if not numbers:
            print(
                "error: this charger reports no per-socket current limit "
                "(0x2129_0); set the station maximum with --station-max",
                file=sys.stderr,
            )
            return EXIT_ERROR
        limits = dict.fromkeys(numbers, args.amps)
        after = controls.apply(
            charger,
            external_sockets=limits if args.external else None,
            sockets=None if args.external else limits,
            state=state,
        )
        changed = ", ".join(f"Socket {n}" for n in numbers)
    if args.external:
        print(
            f"{changed}: external request set to {args.amps:g} A "
            "(not stored; the charger forgets it on the next boot)."
        )
    else:
        print(f"{changed} set to {args.amps:g} A.")
    _report_control_warnings(after)
    return EXIT_OK


def cmd_brightness(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show or set the LED and display brightness (the app's Intensity panel)."""
    state = controls.read(charger)
    if args.action == "show":
        print_rows("Display and LED brightness", controls.format_brightness(state))
        print("\nSet it with: alfenctl brightness set 40")
        return EXIT_OK

    if args.level is None and args.auto is None:
        print(
            "error: give a brightness (0-100), --auto on/off, or both",
            file=sys.stderr,
        )
        return EXIT_ERROR
    after = controls.apply(
        charger,
        intensity=args.level,
        auto_dim=None if args.auto is None else args.auto == "on",
        state=state,
    )
    print_rows("Display and LED brightness", controls.format_brightness(after))
    return EXIT_OK


def cmd_socket(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Take a socket out of service, or put it back (the 0x205F bit field)."""
    reading = controls.read_socket_flags(charger)
    if reading is None:
        print(
            "error: this charger does not report the socket status flags "
            "(0x205F_0), so a socket cannot be taken out of service",
            file=sys.stderr,
        )
        return EXIT_ERROR
    flags, _data_type = reading
    if args.action == "show":
        # Which sockets exist is the charger's answer, not this table's: a
        # single-socket station should not be told about a socket 2.
        present = sorted(controls.read(charger).sockets) or [1]
        numbers = [args.socket] if args.socket else present
        rows = [
            (
                "Station",
                "out of service"
                if flags & status.STATION_INOPERATIVE_BIT
                else "in service",
            )
        ]
        for number in numbers:
            rows.append(
                (
                    f"Socket {number}",
                    "out of service"
                    if flags & status.socket_inoperative_bit(number)
                    else "in service",
                )
            )
        print_rows("Sockets", rows)
        return EXIT_OK

    operative = args.action == "enable"
    number = args.socket or 1
    if not operative and not args.yes:
        print(
            "Taking a socket out of service stops any session charging on it.",
            file=sys.stderr,
        )
        if not confirm(f"Disable socket {number}?"):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    after = controls.set_socket_operative(charger, number, operative, flags=flags)
    where = "back in service" if operative else "out of service"
    print(f"Socket {number} is {where}.")
    if after == flags:
        print("(it already was; nothing was written)", file=sys.stderr)
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "current",
        help="show or set the charging current limits",
        description="Show or set the current limits the app's Power panel "
        "writes: the maximum for the whole station (0x2062_0) and the maximum "
        "for each socket (0x2129_0, 0x3129_0). With no ACTION, shows them.",
    )
    csub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    cc = csub.add_parser("show", help="show the current limits", parents=[common])
    cc = csub.add_parser("set", help="set a current limit, in amps", parents=[common])
    cc.add_argument(
        "amps",
        type=float,
        metavar="AMPS",
        help=f"the limit in amps ({controls.MIN_CURRENT_A:g}-"
        f"{controls.MAX_CURRENT_A:g})",
    )
    cc.add_argument(
        "--socket",
        type=int,
        metavar="N",
        choices=sorted(controls.SOCKET_MAX_CURRENT),
        help="only this socket (default: every socket the charger reports)",
    )
    cc.add_argument(
        "--station-max",
        action="store_true",
        help="set the maximum for the whole station instead of a socket's",
    )
    cc.add_argument(
        "--external",
        action="store_true",
        help="write the external controller's request (0x212A_0) rather than "
        "the stored socket maximum; not kept across a reboot",
    )

    sp = sub.add_parser(
        "socket",
        help="take a socket out of service, or put it back",
        description="Show or change which sockets are in service. The charger "
        "keeps this as one bit field (0x205F_0) holding every socket's bit and "
        "the station's own, so a change here is a read-modify-write and leaves "
        "the other sockets alone. With no ACTION, shows them.",
    )
    ssub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    for name, helptext in (
        ("show", "show which sockets are in service"),
        ("enable", "put a socket back in service"),
        ("disable", "take a socket out of service"),
    ):
        sc = ssub.add_parser(name, help=helptext, parents=[common])
        sc.add_argument(
            "socket",
            type=int,
            nargs="?",
            metavar="N",
            choices=sorted(controls.SOCKET_MAX_CURRENT),
            help="which socket (default: 1)" if name != "show" else "only this socket",
        )
        if name == "disable":
            sc.add_argument("-y", "--yes", action="store_true", help="do not prompt")

    sp = sub.add_parser(
        "brightness",
        help="show or set the display and LED brightness",
        description="Show or set what the app calls Intensity: the LED and "
        "display brightness (0x2061_2) and whether the charger dims itself "
        "(0x2061_1). With no ACTION, shows them.",
    )
    bsub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    bc = bsub.add_parser("show", help="show the brightness settings", parents=[common])
    bc = bsub.add_parser(
        "set", help="set the brightness, the auto-dim, or both", parents=[common]
    )
    bc.add_argument(
        "level",
        type=int,
        nargs="?",
        metavar="PERCENT",
        help=f"brightness in percent ({controls.MIN_INTENSITY}-"
        f"{controls.MAX_INTENSITY})",
    )
    bc.add_argument(
        "--auto",
        choices=("on", "off"),
        help="whether the charger dims itself when nothing is happening",
    )


COMMANDS: dict[str, Command] = {
    "current": Command(cmd_current),
    "brightness": Command(cmd_brightness),
    "socket": Command(cmd_socket),
}
