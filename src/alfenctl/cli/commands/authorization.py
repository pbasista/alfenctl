"""``alfenctl auth`` -- who may start a session on this charger.

The companion to ``alfenctl tags``, which manages the list but could never
turn it on.  The two settings worth naming here rather than writing by id are
the mode, which decides whether a tag is read at all, and the offline action,
which is one choice stored as two registers.
"""

from __future__ import annotations

import argparse
import sys

from alfenctl import authorization
from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_OK
from alfenctl.cli.output import note_reboot_required, print_rows

# What the two enumerations are called on the command line, so that nobody has
# to remember that RFID is 2 and "accept any tag" is 3.
MODE_WORDS = {
    "plug-and-charge": authorization.MODE_PLUG_AND_CHARGE,
    "rfid": authorization.MODE_RFID,
}
# The one setting here the charger accepts and then ignores until it
# restarts; the key is this command's own flag (values.REBOOT_REQUIRED_KEYS).
REBOOT_ARGS = {"mode": authorization.P_MODE}

OFFLINE_WORDS = {
    "refuse": authorization.OFFLINE_REFUSE_ALL,
    "known": authorization.OFFLINE_ACCEPT_KNOWN,
    "any": authorization.OFFLINE_ACCEPT_ALL,
}


def _report_warnings(state: authorization.Authorization) -> None:
    """Print what the charger accepted but will not act on as it looks."""
    for caveat in state.warnings():
        print(f"warning: {caveat}", file=sys.stderr)


def _on_off(value: str | None) -> bool | None:
    """Turn an ``on``/``off`` argument into a flag, leaving None alone."""
    return None if value is None else value == "on"


def cmd_auth(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show or set the authorization settings."""
    if args.action == "show":
        state = authorization.read(charger)
        print_rows("Authorization", state.rows())
        _report_warnings(state)
        return EXIT_OK
    state = authorization.apply(
        charger,
        mode=MODE_WORDS.get(args.mode) if args.mode else None,
        plug_and_charge_id=args.plug_and_charge_id,
        whitelist=_on_off(args.whitelist),
        local_list=_on_off(args.local_list),
        restart_after_outage=_on_off(args.restart_after_outage),
        max_outage_s=args.max_outage,
        remote_tx_requests=_on_off(args.remote_start),
        stop_on_invalid_tag=_on_off(args.stop_on_invalid_tag),
        abort_concurrent=_on_off(args.abort_concurrent),
        connection_timeout_s=args.connection_timeout,
        authorization_timeout_s=args.authorization_timeout,
        online_action=args.online_action,
        offline_action=OFFLINE_WORDS.get(args.offline) if args.offline else None,
    )
    print_rows("Authorization", state.rows())
    _report_warnings(state)
    note_reboot_required(
        key for name, key in REBOOT_ARGS.items() if getattr(args, name, None)
    )
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "auth",
        help="show or set who may start a charging session",
        aliases=["authorization"],
        description="Show or set what the app's Authorization panel writes: "
        "the authorization method (0x2126_0), whether the local whitelist and "
        "the OCPP local list are consulted (0x213B_0, 0x213D_0), and what to "
        "do with a tag while the backoffice is unreachable (0x2127_0 and "
        "0x213E_0, which the app reads as one setting). The tags themselves "
        "are `alfenctl tags`. With no ACTION, shows them.",
    )
    asub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    asub.add_parser("show", help="show the authorization settings", parents=[common])
    ac = asub.add_parser("set", help="change one or more settings", parents=[common])
    onoff = ("on", "off")
    ac.add_argument(
        "--mode", choices=sorted(MODE_WORDS), help="how a driver identifies themselves"
    )
    ac.add_argument(
        "--offline",
        choices=list(OFFLINE_WORDS),
        help="what to do with a tag when the backoffice cannot be reached",
    )
    ac.add_argument(
        "--online-action",
        type=int,
        metavar="N",
        help="what to do when it can: "
        + ", ".join(
            f"{v} ({n})" for v, n in sorted(authorization.ONLINE_ACTIONS.items())
        ),
    )
    ac.add_argument("--whitelist", choices=onoff, help="consult the local whitelist")
    ac.add_argument("--local-list", choices=onoff, help="consult the OCPP local list")
    ac.add_argument(
        "--plug-and-charge-id",
        metavar="ID",
        help="the id to report for an unidentified car",
    )
    ac.add_argument(
        "--restart-after-outage",
        choices=onoff,
        help="resume a session after a power cut",
    )
    ac.add_argument(
        "--max-outage", type=int, metavar="S", help="how long such an outage may last"
    )
    ac.add_argument(
        "--remote-start",
        choices=onoff,
        help="accept RemoteStartTransaction from the backoffice",
    )
    ac.add_argument(
        "--stop-on-invalid-tag",
        choices=onoff,
        help="stop when a tag turns out to be bad",
    )
    ac.add_argument(
        "--abort-concurrent", choices=onoff, help="abort a concurrent transaction"
    )
    ac.add_argument(
        "--connection-timeout",
        type=int,
        metavar="S",
        help="how long to wait for the car",
    )
    ac.add_argument(
        "--authorization-timeout",
        type=int,
        metavar="S",
        help="how long an authorisation lasts",
    )


COMMANDS: dict[str, Command] = {
    "auth": Command(cmd_auth),
    "authorization": Command(cmd_auth),
}
