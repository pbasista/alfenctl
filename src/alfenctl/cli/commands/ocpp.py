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

from alfenctl import ocpp
from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_OK
from alfenctl.cli.output import note_reboot_required, print_rows


# The settings the charger accepts and then ignores until it restarts, keyed
# by this command's own flag (values.REBOOT_REQUIRED_KEYS).
REBOOT_ARGS = {
    "protocol": ocpp.P_PROTOCOL,
    "wired_url": ocpp.P_WIRED_URL,
    "mobile_url": ocpp.P_MOBILE_URL,
    "proxy": ocpp.P_PROXY_ENABLED,
}


def _report_warnings(state: ocpp.Ocpp) -> None:
    """Print what the charger accepted but will not act on as it looks."""
    for caveat in state.warnings():
        print(f"warning: {caveat}", file=sys.stderr)


def _on_off(value: str | None) -> bool | None:
    """Turn an ``on``/``off`` argument into a flag, leaving None alone."""
    return None if value is None else value == "on"


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
    state = ocpp.apply(
        charger,
        connect_method=args.connect_method,
        protocol=args.protocol,
        wired_url=args.wired_url,
        wired_path=args.wired_path,
        mobile_url=args.mobile_url,
        mobile_path=args.mobile_path,
        heartbeat_s=args.heartbeat,
        ping_pong_s=args.ping_pong,
        meter_interval_s=args.meter_interval,
        aligned_interval_s=args.aligned_interval,
        send_station_status=_on_off(args.send_station_status),
        status_mode=args.status_mode,
        info_notifications=_on_off(args.info_notifications),
        tx_attempts=args.tx_attempts,
        tx_retry_s=args.tx_retry,
        cpo_name=args.cpo_name,
        security_profile=args.security_profile,
        proxy_enabled=_on_off(args.proxy),
        proxy_address=args.proxy_address,
        proxy_user=args.proxy_user,
    )
    print_rows("OCPP", state.rows())
    _report_warnings(state)
    note_reboot_required(
        key
        for name, key in REBOOT_ARGS.items()
        if getattr(args, name, None) is not None
    )
    return EXIT_OK


def _enum_help(table: dict[int, str]) -> str:
    """Render an enumeration as ``value (label)`` pairs for a help string."""
    return ", ".join(f"{value} ({label})" for value, label in sorted(table.items()))


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
    onoff = ("on", "off")
    oc.add_argument(
        "--connect-method",
        type=int,
        metavar="N",
        help=f"how to dial out: {_enum_help(ocpp.CONNECT_METHODS)}",
    )
    oc.add_argument("--protocol", choices=ocpp.PROTOCOLS, help="the OCPP version")
    oc.add_argument("--wired-url", metavar="URL", help="the CSMS host and port, wired")
    oc.add_argument("--wired-path", metavar="PATH", help="its path, wired")
    oc.add_argument(
        "--mobile-url", metavar="URL", help="the CSMS host and port, mobile"
    )
    oc.add_argument("--mobile-path", metavar="PATH", help="its path, mobile")
    oc.add_argument(
        "--heartbeat",
        type=int,
        metavar="S",
        help="the heartbeat interval to ask for (0x2085_0; the negotiated one "
        "at 0x2086_0 is read-only)",
    )
    oc.add_argument(
        "--ping-pong", type=int, metavar="S", help="websocket ping interval"
    )
    oc.add_argument(
        "--meter-interval", type=int, metavar="S", help="how often to send meter values"
    )
    oc.add_argument(
        "--aligned-interval", type=int, metavar="S", help="the clock-aligned interval"
    )
    oc.add_argument(
        "--send-station-status", choices=onoff, help="send the station's own status"
    )
    oc.add_argument(
        "--status-mode",
        type=int,
        metavar="N",
        help=f"status notifications: {_enum_help(ocpp.STATUS_MODES)}",
    )
    oc.add_argument(
        "--info-notifications", choices=onoff, help="send informational notifications"
    )
    oc.add_argument(
        "--tx-attempts", type=int, metavar="N", help="transaction message attempts"
    )
    oc.add_argument("--tx-retry", type=int, metavar="S", help="the retry interval")
    oc.add_argument(
        "--cpo-name", metavar="NAME", help="the operator name on the certificate"
    )
    oc.add_argument(
        "--security-profile",
        type=int,
        metavar="N",
        help=f"OCPP security: {_enum_help(ocpp.SECURITY_PROFILES)}",
    )
    oc.add_argument("--proxy", choices=onoff, help="use an HTTP proxy")
    oc.add_argument("--proxy-address", metavar="HOST:PORT", help="the proxy's address")
    oc.add_argument("--proxy-user", metavar="NAME", help="the proxy user name")


COMMANDS: dict[str, Command] = {"ocpp": Command(cmd_ocpp)}
