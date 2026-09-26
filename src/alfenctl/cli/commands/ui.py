"""``alfenctl ui`` -- serve the web interface, and what ``alfenctl`` does alone.

The web interface is this program's main way of being used, so it is what
running the bare name does: ``alfenctl`` is ``alfenctl ui``, and every
option this command takes can be given straight after it.  The rewrite is
:func:`~alfenctl.cli.parser.insert_default_command`.

The only command that opens no charger session of its own: the server
makes one when a browser asks for something that needs it, and hands it
back when nobody is looking.
"""

from __future__ import annotations

import argparse
import sys

from devicectl.cli.command import Command, Need

from alfenctl.charger import AlfenCharger
from alfenctl.cli.exits import EXIT_ERROR
from alfenctl.cli.output import error
from alfenctl.cli.target import resolve_target
from alfenctl.config import load_config


def cmd_ui(charger: AlfenCharger | None, args: argparse.Namespace) -> int:
    """Serve the web UI (no charger session: the server makes its own)."""
    from devicectl.web.server import parse_listen

    from alfenctl.web import DEFAULT_HOST, DEFAULT_PORT, serve
    from alfenctl.web.session import Target

    config = load_config(args.config)
    try:
        host, port = parse_listen(
            args.listen, default_host=DEFAULT_HOST, default_port=DEFAULT_PORT
        )
    except ValueError:
        error(f"cannot read --listen '{args.listen}'")
        return EXIT_ERROR
    try:
        station, username, password = resolve_target(args, config)
    except ValueError as exc:
        error(str(exc))
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
        help="serve the web interface (this is what alfenctl does with no arguments)",
        description="Serve the web interface on this machine, which is what "
        "alfenctl does when it is run with no command at all. The server keeps "
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
