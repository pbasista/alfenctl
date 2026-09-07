"""``alfenctl ui`` -- serve the web interface.

The only command that opens no charger session of its own: the server
makes one when a browser asks for something that needs it, and hands it
back when nobody is looking.
"""

from __future__ import annotations

import argparse
import sys

from alfenctl.config import load_config
from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Command, Need
from alfenctl.cli.exits import EXIT_ERROR
from alfenctl.cli.target import resolve_target


def _parse_listen(text: str) -> tuple[str, int]:
    """Split ``--listen`` into a host and a port.

    Takes ``HOST``, ``HOST:PORT``, ``[v6]:PORT`` or a bare ``PORT``, so
    ``--listen 9000`` and ``--listen 0.0.0.0`` both mean what they look like.
    """
    from alfenctl.web import DEFAULT_HOST, DEFAULT_PORT

    raw = text.strip()
    if not raw:
        return DEFAULT_HOST, DEFAULT_PORT
    if raw.isdigit():
        return DEFAULT_HOST, int(raw)
    if raw.startswith("["):  # [::1] or [::1]:8088
        host, _, rest = raw[1:].partition("]")
        port = rest.lstrip(":")
        return host, int(port) if port else DEFAULT_PORT
    host, sep, port = raw.rpartition(":")
    if not sep or not port.isdigit():
        return raw, DEFAULT_PORT
    return host or DEFAULT_HOST, int(port)


def cmd_ui(charger: AlfenCharger | None, args: argparse.Namespace) -> int:
    """Serve the web UI (no charger session: the server makes its own)."""
    from alfenctl.web import serve
    from alfenctl.web.session import Target

    config = load_config(args.config)
    try:
        host, port = _parse_listen(args.listen)
    except ValueError:
        print(f"error: cannot read --listen '{args.listen}'", file=sys.stderr)
        return EXIT_ERROR
    try:
        station, username, password = resolve_target(args, config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    target = None
    if station is not None:
        target = Target(
            station=station,
            username=username,
            password=password,
            label=args.station or station.object_id or station.ip,
            debug=args.debug,
        )
    elif args.station or args.host:
        print(
            f"No station found for '{args.station or args.host}'; "
            "pick one in the browser instead.",
            file=sys.stderr,
        )
    return serve(
        target=target,
        config=config,
        host=host,
        port=port,
        token="" if args.no_token else args.token,
        read_only=args.read_only,
        open_browser=not args.no_browser,
        poll_interval=args.poll_interval,
        idle_timeout=args.idle_timeout,
        allow_hosts=tuple(args.allow_host or ()),
        discover_time=args.discover_time,
        debug=args.debug,
    )


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "ui",
        help="serve the web interface in a browser",
        description="Serve the web interface on this machine. The server keeps "
        "the one connection the charger allows and shows every open page what "
        "it is doing, so several people can watch the same station.",
        parents=[common],
    )
    sp.add_argument(
        "--listen",
        default="",
        metavar="ADDR",
        help="where to serve: PORT, HOST, or HOST:PORT (default 127.0.0.1:8088)",
    )
    sp.add_argument(
        "--read-only",
        action="store_true",
        help="refuse every change from the browser (safe to share)",
    )
    sp.add_argument(
        "--token",
        default=None,
        help="access token for a non-loopback address (default: generated)",
    )
    sp.add_argument(
        "--no-token",
        action="store_true",
        help="serve without an access token, even off loopback",
    )
    sp.add_argument(
        "--allow-host",
        action="append",
        metavar="NAME",
        help="also answer to this hostname (repeatable; IPs always work)",
    )
    sp.add_argument(
        "--no-browser", action="store_true", help="do not open a browser window"
    )
    sp.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        metavar="S",
        help="seconds between live refreshes (default 3)",
    )
    sp.add_argument(
        "--idle-timeout",
        type=float,
        default=None,
        metavar="S",
        help="seconds before an unused connection is handed back (default 45)",
    )


COMMANDS: dict[str, Command] = {
    "ui": Command(cmd_ui, needs=Need.NOTHING),
}
