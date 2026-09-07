"""Who may talk to the charger: passwords, and write-only keys.

``password recover`` is the odd one out in the whole program -- it runs
without logging in, because the point of it is that the password is not
known.  See :class:`alfenctl.cli.command.Need`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

import httpx

from alfenctl import secret
from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Command, Need
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import print_table

# DlgEndUserPin's own validation, mirrored client-side.
PIN_RE = re.compile(r"^[0-9]{4,6}$")

# Default lifetime of a temporary password; the app's dialog offers 1..72 hours.
DEFAULT_TEMP_PASSWORD_HOURS = 24

# HTTP statuses the recovery endpoint answers with (ICULanDevice.ResetPassword).
HTTP_FORBIDDEN = 403

HTTP_TOO_MANY_REQUESTS = 429

HTTP_SERVICE_UNAVAILABLE = 503

SECONDS_PER_MINUTE = 60


def _recovery_error(exc: httpx.HTTPStatusError) -> str:
    """Turn the charger's refusal of a reset code into the app's wording."""
    status = exc.response.status_code
    if status == HTTP_FORBIDDEN:
        return "the password reset code is incorrect."
    if status == HTTP_TOO_MANY_REQUESTS:
        try:
            body = json.loads(exc.response.text.replace('{"version":1,', "{"))
            left = float(body.get("lockout_remaining_seconds", 0))
        except (ValueError, TypeError):
            left = 0
        wait = f" for {left / SECONDS_PER_MINUTE:.1f} minutes" if left > 0 else ""
        return f"locked out{wait} after too many incorrect reset attempts."
    if status == HTTP_SERVICE_UNAVAILABLE:
        return "password recovery is not available on this charging station."
    return f"the charger refused the reset code (HTTP {status})."


def cmd_password(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Change, time-limit, or recover the charger's login password."""
    import getpass

    if args.action == "recover":
        try:
            charger.reset_password(args.code)
        except httpx.HTTPStatusError as exc:
            print(f"error: {_recovery_error(exc)}", file=sys.stderr)
            return EXIT_ERROR
        print(
            "The password has been reset to the charger's default.\n"
            "Log in with it and set a new one: alfenctl password set"
        )
        return EXIT_OK

    if args.action == "pin":
        if args.disable:
            charger.disable_end_user_access()
            print("Eve Connect app access disabled.")
            return EXIT_OK
        if args.allow_empty:
            charger.set_end_user_pin("")
            print("Eve Connect app access enabled without a PIN.")
            return EXIT_OK
        pin = args.pin or getpass.getpass("New PIN (4-6 digits): ")
        if not PIN_RE.match(pin):
            print("error: the PIN must be 4 to 6 digits", file=sys.stderr)
            return EXIT_ERROR
        charger.set_end_user_pin(pin)
        print("Eve Connect app access PIN set.")
        return EXIT_OK

    new_password = args.password or getpass.getpass("New password: ")
    if not new_password:
        print("error: empty password", file=sys.stderr)
        return EXIT_ERROR
    if args.action == "temporary":
        charger.set_temporary_password(new_password, args.hours)
        print(
            f"Temporary password set; the charger reverts to the previous one "
            f"in {args.hours} hour(s)."
        )
        return EXIT_OK
    charger.set_password(new_password)
    print("Password changed. Update alfen.toml so the next run can log in.")
    return EXIT_OK


def cmd_secret_list(args: argparse.Namespace) -> int:
    """List the secrets that can be installed (no charger needed)."""
    print(
        "Secrets that can be installed (write-only: the charger never reads "
        "them back):\n"
    )
    rows = [
        (
            s.name,
            "FILE" if s.takes_file else "VALUE",
            s.summary + ("" if s.verified else " *"),
        )
        for s in secret.SECRETS
    ]
    print_table(["NAME", "TAKES", "WHAT IT IS"], [list(r) for r in rows])
    if any(not s.verified for s in secret.SECRETS):
        print(
            "\n* item type known from the app's own table, but the app itself "
            "never sends it,\n  so it is untested against a live charger."
        )
    print("\nInstall one with: alfenctl secret set <name> [VALUE|FILE]")
    return EXIT_OK


def cmd_secret(charger: AlfenCharger | None, args: argparse.Namespace) -> int:
    """List the installable secrets, or install one."""
    import getpass

    if args.action == "list":
        return cmd_secret_list(args)
    assert charger is not None  # every other action needs a session

    item = secret.find(args.name)
    if item.takes_file:
        if not args.value:
            print(
                f"error: {item.name} takes a file: "
                f"alfenctl secret set {item.name} <file.pem>",
                file=sys.stderr,
            )
            return EXIT_ERROR
        data = secret.read_file(args.value)
        source = f"from {args.value}"
    else:
        # Prompt rather than take it on the command line, so a secret
        # need not pass through the shell's history (as `password` does).
        value = args.value or getpass.getpass(f"New {item.name}: ")
        data = value.encode()
        source = ""
    secret.install(charger, item, data)
    info = charger.basic_info()
    print(f"Installed {item.name} on {info.object_id}{' ' + source if source else ''}.")
    print("The charger applies it on its next restart: alfenctl reboot")
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "password",
        help="change or recover the login password",
        description="Change or recover the login password. This command has "
        "no default ACTION: every one of them changes something.",
    )
    # As with `tags`, the connection options go on each action.
    pw = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    pp = pw.add_parser("set", help="set a new login password", parents=[common])
    pp.add_argument(
        "password", nargs="?", help="the new password (prompted for if omitted)"
    )
    pp = pw.add_parser(
        "temporary", help="set a password that expires by itself", parents=[common]
    )
    pp.add_argument(
        "password", nargs="?", help="the new password (prompted for if omitted)"
    )
    pp.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_TEMP_PASSWORD_HOURS,
        help=f"hours until the charger reverts to the previous password "
        f"(default {DEFAULT_TEMP_PASSWORD_HOURS})",
    )
    pp = pw.add_parser(
        "recover",
        help="reset to the default password with the code on the charger",
        parents=[common],
    )
    pp.add_argument("code", help="the password reset code printed on the charger")
    pp = pw.add_parser(
        "pin", help="set or disable the Eve Connect app access PIN", parents=[common]
    )
    pp.add_argument("pin", nargs="?", help="new PIN, 4 to 6 digits")
    pin_mode = pp.add_mutually_exclusive_group()
    pin_mode.add_argument(
        "--allow-empty",
        action="store_true",
        help="enable app access without requiring a PIN",
    )
    pin_mode.add_argument(
        "--disable", action="store_true", help="disable app access entirely"
    )

    sp = sub.add_parser(
        "secret",
        help="install a key or certificate that properties cannot carry",
        description="Install one of the write-only secrets the charger keeps "
        "outside the property API: the OCPP authorization key, the proxy "
        "password, TLS certificates. Nothing here can be read back. With no "
        "ACTION, lists what can be installed.",
    )
    ssub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    sc = ssub.add_parser(
        "list",
        help="show which secrets can be installed (no charger needed)",
        parents=[common],
    )
    sc = ssub.add_parser("set", help="install one secret", parents=[common])
    sc.add_argument(
        "name",
        metavar="NAME",
        choices=[s.name for s in secret.SECRETS],
        help="which secret (see 'alfenctl secret')",
    )
    sc.add_argument(
        "value",
        nargs="?",
        metavar="VALUE|FILE",
        help="the value, or the certificate file; a value is prompted for "
        "if omitted, so it need not go through your shell history",
    )


COMMANDS: dict[str, Command] = {
    "password": Command(cmd_password, per_action={"recover": Need.CONNECTION}),
    "secret": Command(cmd_secret, per_action={"list": Need.NOTHING}),
}
