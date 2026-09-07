"""``alfenctl scn`` -- Smart Charging Network membership.

The only command group that talks to more than one charger.  Membership is
a property block each member holds about the whole network, so joining or
leaving means writing to every peer, not just to this one -- and a peer
that cannot be reached leaves the network inconsistent, which is why every
write here is reported one by one.
"""

from __future__ import annotations

from collections.abc import Mapping

import argparse
import sys
from typing import Any

import httpx

from alfenctl import scn
from alfenctl.charger import AlfenCharger
from alfenctl.discovery import Station, discover
from alfenctl.upgrade import DEFAULT_REBOOT_TIMEOUT_S

from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import confirm
from alfenctl.cli.report import wait_for_reboot


def _scn_probe_peers(
    args: argparse.Namespace, exclude_ip: str, username: str, password: str
) -> list[tuple[Station, scn.Peer]]:
    """Log into every other charger the LAN offers and read its SCN membership.

    A station that does not answer, or rejects these credentials, is
    skipped with a warning rather than failing the whole command -- it is
    as likely to be unrelated hardware on the same LAN as it is to be an
    unreachable member (see the module docstring in :mod:`alfenctl.scn` for
    why alfenctl, unlike the app, cannot tell those two apart without a
    login).
    """
    found: list[tuple[Station, scn.Peer]] = []
    for station in discover(args.discover_time):
        if station.ip == exclude_ip:
            continue
        peer = AlfenCharger(station, username, password, debug=args.debug)
        try:
            peer.login()
            membership = scn.read_membership(peer)
            info = peer.basic_info()
        except httpx.HTTPError as exc:
            print(
                f"warning: could not log into {station.object_id} "
                f"({station.ip}): {exc}",
                file=sys.stderr,
            )
            continue
        finally:
            peer.close()
        found.append(
            (
                station,
                scn.Peer(
                    object_id=info.object_id,
                    identity=info.identity or info.object_id,
                    own_sockets=info.sockets or 1,
                    membership=membership,
                ),
            )
        )
    return found


def _scn_write_to_peer(
    station: Station,
    username: str,
    password: str,
    args: argparse.Namespace,
    writes: Mapping[tuple[int, int], tuple[Any, int | None]],
) -> bool:
    """Log into one other member and apply ``writes``; ``False`` on failure."""
    peer = AlfenCharger(station, username, password, debug=args.debug)
    try:
        peer.login()
        peer.write_properties(writes)
    except httpx.HTTPError as exc:
        print(
            f"warning: could not update {station.object_id} ({station.ip}): {exc}",
            file=sys.stderr,
        )
        return False
    finally:
        peer.close()
    return True


def _sync_other_members(
    members: list[tuple[Station, scn.Peer]],
    total: int,
    settings_: scn.ScnSettings,
    args: argparse.Namespace,
    username: str,
    password: str,
) -> None:
    """Push the new total socket count and shared settings to every member."""
    if not members:
        return
    writes = scn.sync_writes(total, settings_)
    ok = sum(
        _scn_write_to_peer(station, username, password, args, writes)
        for station, _peer in members
    )
    print(f"Updated {ok}/{len(members)} other member(s) with the new total.")


def cmd_scn(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show, create, join, or leave a Smart Charging Network."""
    if args.action == "status":
        return _cmd_scn_status(charger, args)
    if args.action == "create":
        return _cmd_scn_create(charger, args)
    if args.action == "join":
        return _cmd_scn_join(charger, args)
    return _cmd_scn_leave(charger, args)


def _print_membership(membership: scn.Membership) -> None:
    s = membership.settings
    print(f"  Socket id       {membership.socket_id}")
    print(f"  Total sockets   {membership.socket_count}")
    print(
        f"  Current limits  {s.total_current_a:g} A total, "
        f"{s.socket_safe_current_a:g} A socket safe, "
        f"{s.total_safe_current_a:g} A total safe"
    )
    print(f"  Alternating     every {s.alternating_period_s} s")


def _cmd_scn_status(charger: AlfenCharger, args: argparse.Namespace) -> int:
    info = charger.basic_info()
    membership = scn.read_membership(charger)
    if not membership.in_network:
        print(f"{info.object_id} is not a member of a Smart Charging Network.")
        return EXIT_OK
    print(
        f"{info.object_id} is a member of Smart Charging Network '{membership.name}':"
    )
    _print_membership(membership)
    if not args.peers:
        print("\nUse --peers to also probe the LAN for the network's other members.")
        return EXIT_OK
    print("\nProbing the LAN for other members...", file=sys.stderr)
    peers = _scn_probe_peers(
        args, charger.station.ip, charger.username, charger.password
    )
    others = [
        (station, peer)
        for station, peer in peers
        if peer.membership.name.strip().lower() == membership.name.strip().lower()
    ]
    others.sort(key=lambda t: t[1].membership.socket_id)
    print(f"\n{len(others) + 1} member(s) found:")
    print(f"  {info.object_id:<14} socket {membership.socket_id}  (this station)")
    for _station, peer in others:
        print(f"  {peer.object_id:<14} socket {peer.membership.socket_id}")
    return EXIT_OK


def _cmd_scn_create(charger: AlfenCharger, args: argparse.Namespace) -> int:
    try:
        name = scn.validate_name(args.name)
    except scn.ScnError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    info = charger.basic_info()
    membership = scn.read_membership(charger)
    if membership.in_network:
        print(
            f"error: {info.object_id} is already a member of "
            f"'{membership.name}'; leave it first",
            file=sys.stderr,
        )
        return EXIT_ERROR
    print("Checking the LAN for a name clash...", file=sys.stderr)
    peers = _scn_probe_peers(
        args, charger.station.ip, charger.username, charger.password
    )
    if any(peer.membership.name.strip().lower() == name.lower() for _s, peer in peers):
        print(
            f"error: the SCN name '{name}' is already in use on the LAN",
            file=sys.stderr,
        )
        return EXIT_ERROR
    if not args.yes:
        if not confirm(
            f"Create Smart Charging Network '{name}' with {info.object_id} as "
            f"its only member? The charger will be rebooted."
        ):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    settings_ = scn.ScnSettings(
        alternating_period_s=args.alternating_period,
        total_current_a=args.total_current,
        socket_safe_current_a=args.socket_safe_current,
        total_safe_current_a=args.total_safe_current,
    )
    charger.write_properties(scn.create_writes(name, info.sockets or 1, settings_))
    print(f"Created '{name}'; rebooting {info.object_id} to apply it.")
    charger.reboot(is_ahp=info.family == "AHP")
    if not wait_for_reboot(charger, deadline_s=args.timeout, debug=args.debug):
        print(
            "The charger did not come back before the timeout; it may still "
            "be starting.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    return EXIT_OK


def _cmd_scn_join(charger: AlfenCharger, args: argparse.Namespace) -> int:
    try:
        name = scn.validate_name(args.name)
    except scn.ScnError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    info = charger.basic_info()
    membership = scn.read_membership(charger)
    if membership.in_network:
        print(
            f"error: {info.object_id} is already a member of "
            f"'{membership.name}'; leave it first",
            file=sys.stderr,
        )
        return EXIT_ERROR
    print("Probing the LAN for the network's other members...", file=sys.stderr)
    peers = _scn_probe_peers(
        args, charger.station.ip, charger.username, charger.password
    )
    members = [
        (station, peer)
        for station, peer in peers
        if peer.membership.name.strip().lower() == name.lower()
    ]
    if not members:
        print(
            f"error: no existing members of '{name}' found on the LAN "
            "(is it spelled right, and are its chargers reachable?); "
            "use 'scn create' to start a new network instead",
            file=sys.stderr,
        )
        return EXIT_ERROR
    members.sort(key=lambda t: t[1].membership.socket_id)
    reference = members[0][1]  # lowest socket id: the network's settings source
    own_sockets = info.sockets or 1
    new_id = scn.next_socket_id([peer for _s, peer in members])
    new_total = sum(peer.own_sockets for _s, peer in members) + own_sockets
    if not args.yes:
        if not confirm(
            f"Join '{name}' ({len(members)} existing member(s)) as "
            f"{info.object_id}? The charger will be rebooted."
        ):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    charger.write_properties(
        scn.join_writes(name, new_id, new_total, reference.membership.settings)
    )
    _sync_other_members(
        members,
        new_total,
        reference.membership.settings,
        args,
        charger.username,
        charger.password,
    )
    print(
        f"Joined '{name}' as {info.object_id} (socket {new_id}); rebooting to apply it."
    )
    charger.reboot(is_ahp=info.family == "AHP")
    if not wait_for_reboot(charger, deadline_s=args.timeout, debug=args.debug):
        print(
            "The charger did not come back before the timeout; it may still "
            "be starting.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    return EXIT_OK


def _cmd_scn_leave(charger: AlfenCharger, args: argparse.Namespace) -> int:
    info = charger.basic_info()
    membership = scn.read_membership(charger)
    if not membership.in_network:
        print(
            f"error: {info.object_id} is not a member of a Smart Charging Network",
            file=sys.stderr,
        )
        return EXIT_ERROR
    name = membership.name
    if not args.yes:
        if not confirm(
            f"Remove {info.object_id} from Smart Charging Network '{name}'?"
        ):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    print("Probing the LAN for the network's other members...", file=sys.stderr)
    peers = _scn_probe_peers(
        args, charger.station.ip, charger.username, charger.password
    )
    remaining = [
        (station, peer)
        for station, peer in peers
        if peer.membership.name.strip().lower() == name.strip().lower()
    ]
    charger.write_properties(scn.leave_writes())
    print(f"{info.object_id} removed from '{name}'.")
    if remaining:
        new_total = sum(peer.own_sockets for _s, peer in remaining)
        _sync_other_members(
            remaining,
            new_total,
            membership.settings,
            args,
            charger.username,
            charger.password,
        )
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "scn",
        help="create, join, leave, or show Smart Charging Network membership",
        description="Create, join, leave, or show Smart Charging Network "
        "membership. With no ACTION, shows this charger's membership.",
    )
    # As with `tags`/`password`, the connection options go on each action.
    scnsub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    sc = scnsub.add_parser(
        "status", help="show this charger's SCN membership", parents=[common]
    )
    sc.add_argument(
        "--peers",
        action="store_true",
        help="also probe the LAN for the network's other members",
    )
    sc = scnsub.add_parser(
        "create",
        help="start a new, single-member Smart Charging Network",
        parents=[common],
    )
    sc.add_argument("name", help=f"network name (max {scn.MAX_NAME_LENGTH} characters)")
    sc.add_argument(
        "--total-current",
        type=float,
        default=scn.DEFAULT_TOTAL_CURRENT_A,
        metavar="A",
        help=f"total max static current (default {scn.DEFAULT_TOTAL_CURRENT_A:g})",
    )
    sc.add_argument(
        "--socket-safe-current",
        type=float,
        default=scn.DEFAULT_SOCKET_SAFE_CURRENT_A,
        metavar="A",
        help=f"per-socket safe current (default {scn.DEFAULT_SOCKET_SAFE_CURRENT_A:g})",
    )
    sc.add_argument(
        "--total-safe-current",
        type=float,
        default=scn.DEFAULT_TOTAL_SAFE_CURRENT_A,
        metavar="A",
        help=f"total safe current (default {scn.DEFAULT_TOTAL_SAFE_CURRENT_A:g})",
    )
    sc.add_argument(
        "--alternating-period",
        type=int,
        default=scn.DEFAULT_ALTERNATING_PERIOD_S,
        metavar="S",
        help=f"alternating period, seconds (default {scn.DEFAULT_ALTERNATING_PERIOD_S})",
    )
    sc.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_REBOOT_TIMEOUT_S,
        metavar="S",
        help="seconds to wait for the reboot",
    )
    sc.add_argument("-y", "--yes", action="store_true", help="do not prompt")
    sc = scnsub.add_parser(
        "join", help="join an existing Smart Charging Network", parents=[common]
    )
    sc.add_argument("name", help="network name to join")
    sc.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_REBOOT_TIMEOUT_S,
        metavar="S",
        help="seconds to wait for the reboot",
    )
    sc.add_argument("-y", "--yes", action="store_true", help="do not prompt")
    sc = scnsub.add_parser(
        "leave",
        help="remove this charger from its Smart Charging Network",
        parents=[common],
    )
    sc.add_argument("-y", "--yes", action="store_true", help="do not prompt")


COMMANDS: dict[str, Command] = {
    "scn": Command(cmd_scn),
}
