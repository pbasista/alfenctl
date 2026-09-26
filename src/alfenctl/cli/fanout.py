"""Running one read over every station ``--station`` named.

``--station garage,drive`` or ``--station all`` runs the read you asked for
against each of them in turn and prints one section each.  One station is
untouched by all of this: same bytes, no heading, the path through
:func:`alfenctl.cli.target.open_charger` it always took.

Three decisions this makes, which are a charger's and not a battery's -- the
same feature over a Modbus bus (:mod:`jkctl.cli.fanout`) answers all three
differently, because there the devices are addresses on one open link:

* **``all`` is the stations named in ``alfen.toml``.**  Not what mDNS can
  find: a browse answers with whatever is on the network, and some of it may
  belong to the neighbours.  A person who has written four stations into
  their configuration file has said which four are theirs.
* **``--host`` with a list is an error.**  ``--host`` is one address; there
  is no reading of "this list of stations, at this one address" worth
  guessing at.
* **Sequentially.**  Each station is a separate HTTPS session and a separate
  login, and the charger serves one at a time; four of them concurrently
  would interleave the output and the ``--debug`` trace of four
  conversations, to save a few seconds.  If that is ever worth having, it is
  worth having deliberately, with somewhere for the output to go.

Only reads fan out, which each command declares for itself
(:attr:`devicectl.cli.command.Command.fans_out`).  A command that writes
keeps its single target: it has a diff to show and a question to ask, and
both belong to one charger.
"""

from __future__ import annotations

import argparse

from devicectl.cli.command import Command, Need
from devicectl.cli.fanout import fan_out
from devicectl.cli.main import Translator

from alfenctl.charger import AlfenCharger
from alfenctl.cli.target import open_named
from alfenctl.config import Config


def fan_out_stations(
    names: list[str],
    args: argparse.Namespace,
    config: Config,
    *,
    command: Command,
    needs: Need,
    translate: Translator | None = None,
) -> int:
    """Run one command against each named station, and combine the results.

    Each station gets its own session, opened and closed around its own
    section of the output, so a station that cannot be reached costs that
    section and not the rest.
    """

    def one(name: str) -> int:
        charger: AlfenCharger = open_named(
            name, args, config, login=needs is Need.READY
        )
        with charger:
            code = command.run(charger, args)
            if needs is Need.READY:
                charger.logout()
            return code

    return fan_out(
        names,
        one,
        key=str,
        heading=str,
        as_json=bool(getattr(args, "json", False)),
        translate=translate,
    )


__all__ = ["fan_out_stations"]
