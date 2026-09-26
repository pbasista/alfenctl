"""``alfenctl ocpp`` -- the backoffice connection, as one command.

The read side answers "why is this charger not talking to its CSMS", which
otherwise takes a dozen `alfenctl get` calls across registers the EDS does
not even name.  The write side stops short of the two things that are not
properties: the authorization key and the proxy password are write-only
domain items, and ``alfenctl secret set`` installs those.
"""

from __future__ import annotations

import argparse
import sys

from devicectl import fields
from devicectl.cli.command import Command

from alfenctl import ocpp
from alfenctl.charger import AlfenCharger
from alfenctl.cli.exits import EXIT_OK
from alfenctl.cli.output import note_reboot_required, print_rows

# The settings the charger accepts and then ignores until it restarts, keyed
# by field name (values.REBOOT_REQUIRED_KEYS).
REBOOT_FIELDS = ("protocol", "wired_url", "mobile_url", "proxy_enabled")


def _report_warnings(state: ocpp.Ocpp) -> None:
    """Print what the charger accepted but will not act on as it looks."""
    for caveat in state.warnings():
        print(f"warning: {caveat}", file=sys.stderr)


def cmd_ocpp(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show or set the backoffice connection settings."""
    if args.action == "show":
        state = ocpp.read(charger)
        rows = state.rows()
        if not rows:
            print(
                "The charger reported none of the back-office properties.",
                file=sys.stderr,
            )
            return EXIT_OK
        print_rows("OCPP", rows)
        _report_warnings(state)
        print(
            "\nThe authorization key and the proxy password are not properties; "
            "install them with `alfenctl secret set`.",
            file=sys.stderr,
        )
        return EXIT_OK
    settings = fields.from_namespace(ocpp.FIELDS, args)
    state = ocpp.apply(charger, settings)
    print_rows("OCPP", state.rows())
    _report_warnings(state)
    table = fields.by_name(ocpp.FIELDS)
    note_reboot_required(
        table[name].address for name in REBOOT_FIELDS if name in settings
    )
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "ocpp",
        help="show or set the backoffice (CSMS) connection",
        description="Show or set what the app's Connectivity panel writes: how "
        "the charger dials out (0x2077_0), which CSMS and over what version "
        "(0x2071_*, 0x2078_*, 0x2082_0), the heartbeat and timeouts, the "
        "status notifications, and the proxy. Most of these are not in the "
        "vendor's EDS, so each write is encoded with the type the charger "
        "itself reports. With no ACTION, shows them.",
    )
    osub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    osub.add_parser("show", help="show the backoffice settings", parents=[common])
    oc = osub.add_parser("set", help="change one or more settings", parents=[common])
    fields.add_arguments(ocpp.FIELDS, oc)


COMMANDS: dict[str, Command] = {
    "ocpp": Command(cmd_ocpp, default_action="show", fans_out=("show",))
}
