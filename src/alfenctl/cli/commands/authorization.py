"""``alfenctl auth`` -- who may start a session on this charger.

The companion to ``alfenctl tags``, which manages the list but could never
turn it on.  The two settings worth naming here rather than writing by id are
the mode, which decides whether a tag is read at all, and the offline action,
which is one choice stored as two registers.
"""

from __future__ import annotations

import argparse
import sys

from devicectl import fields
from devicectl.cli.command import Command

from alfenctl import authorization
from alfenctl.charger import AlfenCharger
from alfenctl.cli.exits import EXIT_OK
from alfenctl.cli.output import note_reboot_required, print_rows

# The one setting here the charger accepts and then ignores until it
# restarts (values.REBOOT_REQUIRED_KEYS).
REBOOT_FIELDS = ("mode",)


def _report_warnings(state: authorization.Authorization) -> None:
    """Print what the charger accepted but will not act on as it looks."""
    for caveat in state.warnings():
        print(f"warning: {caveat}", file=sys.stderr)


def cmd_auth(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show or set the authorization settings."""
    if args.action == "show":
        state = authorization.read(charger)
        print_rows("Authorization", state.rows())
        _report_warnings(state)
        return EXIT_OK
    settings = fields.from_namespace(authorization.FIELDS, args)
    state = authorization.apply(charger, settings)
    print_rows("Authorization", state.rows())
    _report_warnings(state)
    table = fields.by_name(authorization.FIELDS)
    note_reboot_required(
        table[name].address for name in REBOOT_FIELDS if name in settings
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
    fields.add_arguments(authorization.FIELDS, ac)


COMMANDS: dict[str, Command] = {
    "auth": Command(cmd_auth, default_action="show", fans_out=("show",)),
    "authorization": Command(cmd_auth, default_action="show", fans_out=("show",)),
}
