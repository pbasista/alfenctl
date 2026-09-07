"""``alfenctl network`` and ``alfenctl wifi`` -- where the charger is reachable.

``wifi`` used to do one thing, scan, and it still does when it is given no
action.  What it could not do was act on what it found: the scan printed three
``alfenctl set`` lines for you to copy.  ``wifi connect`` writes those three
registers itself, with the SSID and key length checked first.

``network show`` is the read side for every interface at once -- Ethernet,
Wi-Fi and the modem -- which is the question ``info`` does not answer.

A scan is the charger's own radio listening, so ``wifi scan`` reads the radio
first and says when the empty list it is about to print means "the radio is
off" rather than "there is nothing out there".  ``wifi scan --enable`` (or
``wifi enable``) switches it on and waits for it to come up.

**And it asks more than once.**  ``/api/wifiscan`` comes back in about three
seconds where the vendor's client allows eleven, which is the shape of an
endpoint that hands back the survey the radio has rather than waiting for a
fresh one.  A radio that has just been switched on has none yet, so an empty
list is retried a few times before it is believed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from alfenctl import network, wifi
from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import print_rows


def cmd_network(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show every interface's address and state."""
    state = network.read(charger)
    rows = state.rows()
    if not rows:
        print("The charger reported none of the network properties.", file=sys.stderr)
        return EXIT_OK
    print_rows("Network", rows)
    return EXIT_OK


def _ready_radio(charger: AlfenCharger, args: argparse.Namespace) -> str | None:
    """Make sure the radio can scan, switching it on when asked to.

    Returns the reason a scan will find nothing, or None when it should
    work.  Without ``--enable`` nothing is written: a charger reached over
    Ethernet has its Wi-Fi off for a reason often enough.
    """
    state = network.read(charger)
    obstacle = state.scan_obstacle()
    if obstacle is None or state.wifi_hardware is False or not args.enable:
        return obstacle
    print("Switching the Wi-Fi radio on...", file=sys.stderr)
    network.enable(charger)
    state = network.wait_for_radio(charger)
    if not state.radio_ready:
        print(
            "warning: the radio is not running yet "
            f"({network.WIFI_STATUSES.get(state.wifi_status or -1, 'unknown')}); "
            "scanning anyway",
            file=sys.stderr,
        )
    return state.scan_obstacle()


# The endpoint answers in about three seconds, well inside the eleven the
# vendor's client allows, so it reports the survey the radio already has
# rather than running one to order.  A radio that has just come up has none.
SCAN_ATTEMPTS = 3
SCAN_RETRY_INTERVAL_S = 4.0


def _scan_repeatedly(charger: AlfenCharger, attempts: int) -> wifi.ScanReply:
    """Scan until something is heard, or the attempts run out.

    Returns the last reply either way -- including its complaints, which are
    the difference between "nothing is out there" and "that was not a scan
    result at all".
    """
    reply = wifi.ScanReply()
    for attempt in range(1, max(1, attempts) + 1):
        reply = wifi.parse_reply(charger.wifi_scan())
        if reply.networks or attempt == attempts:
            return reply
        print(
            f"Nothing heard yet; scanning again ({attempt + 1}/{attempts})...",
            file=sys.stderr,
        )
        time.sleep(SCAN_RETRY_INTERVAL_S)
    return reply


def _explain_empty(reply: wifi.ScanReply, obstacle: str | None) -> None:
    """Say why the list is empty, as precisely as the reply allows."""
    if obstacle:
        # The endpoint answered, and answered nothing, because the radio
        # doing the listening is not on.  That is not an empty band.
        print(
            f"note: {obstacle}.\n"
            "A scan is the charger's own radio listening, so it finds nothing "
            "while the radio is off.\n"
            "Switch it on and scan again with:\n"
            "  alfenctl wifi scan --enable",
            file=sys.stderr,
        )
        return
    detail = reply.summary()
    if reply.complaint:
        print(
            f"note: {detail}.\n"
            "That is not an empty band but an answer this parser did not "
            "recognise; `--debug` prints it verbatim.",
            file=sys.stderr,
        )
        return
    if detail:
        print(f"note: {detail}.", file=sys.stderr)
    print(
        "The radio is on and heard nothing. What is left to check:\n"
        "  - the band: a router broadcasting that SSID only on 5 GHz is "
        "inaudible to a 2.4 GHz radio\n"
        "  - the distance: the charger's antenna is inside a metal case, "
        "outdoors, often behind a wall\n"
        "  - the moment: try `alfenctl wifi scan` again in a minute, or after "
        "`alfenctl reboot` if the radio was only just switched on",
        file=sys.stderr,
    )


def _scan(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Scan for nearby Wi-Fi networks (the app's 'Scan Wi-Fi networks' button)."""
    obstacle = _ready_radio(charger, args)
    reply = _scan_repeatedly(charger, args.attempts)
    networks = reply.networks
    if not networks:
        _explain_empty(reply, obstacle)
    elif (detail := reply.summary()) is not None:
        print(f"note: {detail}.", file=sys.stderr)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "ssid": n.ssid,
                        "signal_dbm": n.signal_dbm,
                        "signal": n.signal_label,
                        "security": n.security_label,
                        "supported": n.supported,
                    }
                    for n in networks
                ],
                indent=2,
            )
        )
        return EXIT_OK
    if not networks:
        print("No Wi-Fi networks found.")
        return EXIT_OK
    width = max(len(n.ssid) for n in networks)
    print(f"{'SSID'.ljust(width)}  SIGNAL       SECURITY")
    for n in networks:
        sec = n.security_label if n.supported else f"{n.security_label} (unsupported)"
        print(
            f"{n.ssid.ljust(width)}  {n.signal_dbm:>4} dBm {n.signal_label:<9}  {sec}"
        )
    print(
        f"\n{len(networks)} network(s). Join one with:\n"
        f"  alfenctl wifi connect '{networks[0].ssid}' --psk <passphrase>"
    )
    return EXIT_OK


def _report(state: network.Network) -> None:
    """Print the Wi-Fi half of a reading, after a change to it."""
    rows = [(label, value) for label, value in state.rows() if "Ethernet" not in label]
    if rows:
        print_rows("Wi-Fi", rows)


def cmd_wifi(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Scan for Wi-Fi networks, join one, or leave."""
    if args.action == "scan":
        return _scan(charger, args)
    if args.action == "connect":
        password = args.psk
        if password is None and not args.open:
            import getpass

            password = getpass.getpass(f"Password for {args.ssid}: ")
        state = network.connect(
            charger, args.ssid, None if args.open else password, security=args.security
        )
        # The charger takes a moment to associate, so what it reports here is
        # the settings it accepted rather than the outcome; say so.
        print(f"Sent the settings for {args.ssid!r}.\n")
        _report(state)
        print(
            "\nThe radio associates in the background; `alfenctl network show` "
            "says whether it got there.",
            file=sys.stderr,
        )
        return EXIT_OK
    if args.action == "enable":
        if network.read(charger).wifi_hardware is False:
            print(
                "error: this charger reports no Wi-Fi radio (0x328F_0 is 0)",
                file=sys.stderr,
            )
            return EXIT_ERROR
        network.enable(charger)
        state = network.wait_for_radio(charger)
        _report(state)
        if not state.radio_ready:
            print(
                "\nThe radio has not reported itself running yet; "
                "`alfenctl network` says when it does.",
                file=sys.stderr,
            )
        return EXIT_OK
    if args.action == "disconnect":
        _report(network.disconnect(charger))
        return EXIT_OK
    if args.action == "ap":
        if args.enable is None and args.start is None:
            print("error: name --enable or --start", file=sys.stderr)
            return EXIT_ERROR
        _report(
            network.set_access_point(
                charger,
                enabled=None if args.enable is None else args.enable == "on",
                start=None if args.start is None else args.start == "on",
            )
        )
        return EXIT_OK
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sub.add_parser(
        "network",
        help="show the charger's Ethernet, Wi-Fi and modem addresses",
        parents=[common],
        description="Show where this charger is on the network. The addresses "
        "are read-only here: writing an interface's own address is how a "
        "station is lost, so it stays an explicit `alfenctl set 207D_2 ...`.",
    )

    sp = sub.add_parser(
        "wifi",
        help="scan for Wi-Fi networks, or join one",
        description="Scan for the networks the charger's radio can see, or "
        "join one by writing wifiSSID (0x328A_0), wifiPSK (0x328B_0) and "
        "sysWifiEnabled (0x3284_0) together. A scan asks the charger's own "
        "radio, so it finds nothing while sysWifiEnabled is 0. With no "
        "ACTION, scans.",
    )
    wsub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    wc = wsub.add_parser("scan", help="list the networks in range", parents=[common])
    wc.add_argument("--json", action="store_true", help="JSON instead of a table")
    wc.add_argument(
        "--enable",
        action="store_true",
        help="switch the radio on first, and wait for it: a scan is the "
        "charger's own radio listening, and finds nothing while it is off",
    )
    wc.add_argument(
        "--attempts",
        type=int,
        default=SCAN_ATTEMPTS,
        metavar="N",
        help=f"how many times to ask before believing an empty list "
        f"(default {SCAN_ATTEMPTS}); the charger reports the survey its radio "
        "already has, which just after a boot is none",
    )
    wc = wsub.add_parser("connect", help="join a network", parents=[common])
    wc.add_argument("ssid", metavar="SSID", help="the network to join")
    # Not --password: the connection options this parser inherits already have
    # one, for the charger's own login.  wifiPSK is the vendor's own name.
    wc.add_argument("--psk", help="its passphrase (prompted for when not given)")
    wc.add_argument(
        "--open", action="store_true", help="the network has no password at all"
    )
    wc.add_argument(
        "--security",
        type=int,
        metavar="N",
        help="the security type, when the default (WPA2-AES) is wrong: "
        + ", ".join(f"{v} ({n})" for v, n in sorted(network.SECURITY_TYPES.items())),
    )
    wc = wsub.add_parser(
        "enable",
        help="switch the radio on, keeping the settings",
        parents=[common],
    )
    wc = wsub.add_parser(
        "disconnect",
        help="switch the radio off, keeping the settings",
        parents=[common],
    )
    wc = wsub.add_parser("ap", help="the charger's own access point", parents=[common])
    wc.add_argument(
        "--enable", choices=("on", "off"), help="start the access point after a boot"
    )
    wc.add_argument("--start", choices=("on", "off"), help="start it now")


COMMANDS: dict[str, Command] = {
    "network": Command(cmd_network),
    "wifi": Command(cmd_wifi),
}
