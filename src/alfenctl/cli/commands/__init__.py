"""The command groups, and the table that maps a typed word to a handler.

Each module here owns one group: the handlers, and the ``add_parsers``
that describes them to argparse.  Adding a command means adding a function
and two lines to the module's own ``COMMANDS`` -- nothing outside this
package changes.

``GROUPS`` is ordered, and that order is the order of ``alfenctl --help``:
finding a charger first, then the things most people came for, then the
narrower ones, then the acts that change the charger itself.
"""

from __future__ import annotations

from devicectl.cli.command import Command

from alfenctl.cli.commands import (
    access,
    authorization,
    cloud,
    config,
    connectivity,
    controls,
    doctor,
    firmware,
    license,
    loadbalancing,
    logs,
    maintenance,
    meter,
    ocpp,
    props,
    scn,
    stations,
    status,
    tags,
    ui,
)

GROUPS = (
    stations,
    config,
    ui,
    props,
    firmware,
    status,
    doctor,
    controls,
    loadbalancing,
    connectivity,
    logs,
    tags,
    authorization,
    ocpp,
    scn,
    meter,
    license,
    cloud,
    access,
    maintenance,
)

COMMANDS: dict[str, Command] = {}
for _group in GROUPS:
    for _name, _command in _group.COMMANDS.items():
        assert _name not in COMMANDS, f"two groups claim the command {_name!r}"
        COMMANDS[_name] = _command

__all__ = ["COMMANDS", "GROUPS"]
