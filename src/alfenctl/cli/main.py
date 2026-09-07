"""Parse the command line, open what the command needs, and run it.

The charger serves one connection at a time, so a command's session is
opened here and given back here -- a command never has to remember to log
out, and a command that needs no session never opens one.
"""

from __future__ import annotations

import ssl
import sys

import httpx

from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Need
from alfenctl.cli.commands import COMMANDS
from alfenctl.cli.exits import EXIT_ERROR, EXIT_INTERRUPTED
from alfenctl.cli.parser import build_parser, insert_default_action
from alfenctl.cli.target import open_charger
from alfenctl.errors import AlfenError


def _run(argv: list[str] | None) -> int:
    """Dispatch one invocation, letting every expected failure reach main()."""
    parser = build_parser()
    argv = insert_default_action(sys.argv[1:] if argv is None else list(argv))
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_ERROR

    command = COMMANDS[args.command]
    needs = command.need(getattr(args, "action", None))
    if needs is Need.NOTHING:
        # The handlers that declare Need.NOTHING are the ones that take
        # `AlfenCharger | None`; the table cannot say which those are.
        return command.run(None, args)  # ty: ignore[invalid-argument-type]

    charger: AlfenCharger | None = open_charger(
        args, parser, login=needs is Need.SESSION
    )
    if charger is None:
        return EXIT_ERROR
    with charger:
        try:
            return command.run(charger, args)
        finally:
            if needs is Need.SESSION:
                charger.logout()  # never had a session to give back otherwise


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, dispatch to the right command, and return an exit code."""
    try:
        return _run(argv)
    except KeyboardInterrupt:
        # Exit at once: a network logout would block tearing down the
        # interrupted connection; the charger drops incomplete work itself.
        print("\nInterrupted.", file=sys.stderr)
        return EXIT_INTERRUPTED
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.read().decode("utf-8", "replace").strip()
        except Exception:
            body = ""
        detail = f": {body}" if body else ""
        print(
            f"error: the charger returned HTTP {exc.response.status_code} "
            f"for {exc.request.url}{detail}",
            file=sys.stderr,
        )
        return EXIT_ERROR
    except httpx.HTTPError as exc:
        print(f"error: cannot reach the charger: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except AlfenError as exc:
        # Every module raises its own subclass of this; none of them needs a
        # handler of its own, because they all end the same way.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (OSError, ssl.SSLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


__all__ = ["main"]
