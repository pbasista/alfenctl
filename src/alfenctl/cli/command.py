"""What one subcommand is: a function to run, and what it needs open first.

The alternative -- a chain of ``if args.command == ...`` -- hid three
different things in the same shape: which function runs, whether a charger
session is needed at all, and whether it has to be logged in.  Two commands
in thirty need less than the rest, and in a chain that is a special case
buried at the top; here it is a field.

The web API's ``ROUTES`` table is the same idea for the same reason.
"""

from __future__ import annotations

import argparse

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from alfenctl.charger import AlfenCharger

# Every handler takes the same two arguments whether it wants them or not,
# so the table can stay one shape.  A handler that declared Need.NOTHING is
# passed None and annotates its first parameter ``AlfenCharger | None``,
# which still satisfies this type: a function accepting more is usable
# wherever one accepting less is.
Handler = Callable[[AlfenCharger, argparse.Namespace], int]


class Need(Enum):
    """What has to be open before a command's handler runs."""

    NOTHING = "nothing"
    """No charger at all: ``list`` browses mDNS, ``ui`` starts a server."""

    CONNECTION = "connection"
    """Connected but not logged in -- for recovering an unknown password."""

    SESSION = "session"
    """Connected and logged in.  Everything else."""


@dataclass(frozen=True)
class Command:
    """One ``alfenctl`` subcommand."""

    run: Handler
    needs: Need = Need.SESSION
    per_action: Mapping[str, Need] = field(default_factory=dict)
    """Actions of this command that need less than the command itself."""

    def need(self, action: str | None) -> Need:
        """Return what this command needs open, given the ACTION it was called with."""
        return self.per_action.get(action or "", self.needs)


__all__ = ["Command", "Handler", "Need"]
