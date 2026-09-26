"""Parse the command line, open what the command needs, and run it.

``alfenctl`` with nothing after it is ``alfenctl ui``: the web interface is
what this program is, and a page of usage text is not what somebody who
typed the bare name came for.  The rewrite is in
:func:`~alfenctl.cli.parser.insert_default_command`, which happens before
argparse sees anything.

The charger serves one connection at a time, so a command's session is
opened here and given back here -- a command never has to remember to log
out, and a command that needs no session never opens one.

Every expected failure lands in :func:`devicectl.cli.main.run`, which prints
one line and returns an exit code.  What is here on top of that is what only
alfenctl can say: an ``httpx`` error is a charger that answered badly or did
not answer at all, and either reads better than the exception underneath it.
"""

from __future__ import annotations

import argparse
import ssl
import sys

import httpx
from devicectl.cli.command import Command, Need
from devicectl.cli.main import run

from alfenctl.charger import AlfenCharger
from alfenctl.cli.commands import COMMANDS
from alfenctl.cli.exits import EXIT_ERROR
from alfenctl.cli.fanout import fan_out_stations
from alfenctl.cli.output import error
from alfenctl.cli.parser import (
    build_parser,
    insert_default_action,
    insert_default_command,
)
from alfenctl.cli.target import open_charger, station_names
from alfenctl.config import Config, load_config


def _run(argv: list[str] | None) -> int:
    """Dispatch one invocation, letting every expected failure reach main()."""
    parser = build_parser()
    argv = insert_default_command(sys.argv[1:] if argv is None else list(argv))
    argv = insert_default_action(argv)
    args = parser.parse_args(argv)
    if args.command is None:  # pragma: no cover - insert_default_command fills it
        parser.print_help()
        return EXIT_ERROR

    action = getattr(args, "action", None)
    command = COMMANDS[args.command]
    needs = command.need(action)
    if needs is Need.NOTHING:
        # A handler that declares Need.NOTHING is passed None and annotates
        # its first parameter `AlfenCharger | None`.  `Handler` leaves that
        # parameter open, because no one signature describes all three levels.
        return command.run(None, args)

    config = load_config(args.config)
    names = _named_stations(args, config, command, action)
    if names is None:
        return EXIT_ERROR
    if names[1:]:
        return fan_out_stations(
            names,
            args,
            config,
            command=command,
            needs=needs,
            translate=_translate,
        )

    charger: AlfenCharger | None = open_charger(args, parser, login=needs is Need.READY)
    if charger is None:
        return EXIT_ERROR
    with charger:
        # Failed or interrupted commands close the connection immediately.
        # A network logout can block and delay reporting the original error;
        # closing the connection also releases the charger's session.
        result = command.run(charger, args)
        if needs is Need.READY:
            charger.logout()
        return result


def _named_stations(
    args: argparse.Namespace,
    config: Config,
    command: Command,
    action: str | None,
) -> list[str] | None:
    """Return the stations named, one or many, or None if the command must stop.

    A command that changes the charger is refused a list rather than run
    over it: each station would want its own diff and its own confirmation,
    and "do this to all four" is not a thing to discover by accident.

    One name is written back onto ``args``, so that ``--station all`` over a
    file naming one station, or a list with a stray comma in it, reaches
    :func:`open_charger` as the name it resolved to.
    """
    try:
        names = station_names(args, config)
    except ValueError as exc:
        error(str(exc))
        return None
    if not names:
        return names
    first, *rest = names
    if not rest:
        # One station, however it was spelled: the path it always took.
        args.station = first
        return names
    if not command.fans_out_for(action):
        typed = " ".join(part for part in (args.command, action) if part)
        error(
            f"'{typed}' can change the charger, so it takes one station at a "
            "time; --station takes a list only for the commands that read."
        )
        return None
    if args.host:
        error("--host is one charger's address; --station named several")
        return None
    if getattr(args, "watch", None):
        # The loop would be inside the fan-out rather than around it: the
        # first station would redraw forever and the rest would never be
        # read.  One station, or one pass over several.
        error("--watch follows one station; it cannot be given a list")
        return None
    return names


def _translate(exc: BaseException) -> str | None:
    """Say what an HTTP failure means, in the charger's terms."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            body = exc.response.read().decode("utf-8", "replace").strip()
        except Exception:  # noqa: BLE001 - a body we cannot read is no body
            body = ""
        detail = f": {body}" if body else ""
        return (
            f"the charger returned HTTP {exc.response.status_code} "
            f"for {exc.request.url}{detail}"
        )
    if isinstance(exc, httpx.HTTPError):
        return f"cannot reach the charger: {exc}"
    if isinstance(exc, ssl.SSLError):
        return str(exc)
    return None


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, dispatch to the right command, and return an exit code."""
    # Interrupted: exit at once.  A network logout would block tearing down
    # the interrupted connection; the charger drops incomplete work itself.
    return run(lambda: _run(argv), translate=_translate)


__all__ = ["main"]
