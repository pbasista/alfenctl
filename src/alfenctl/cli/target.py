"""Which charger a command talks to, and as whom.

The answer can come from four places -- the command line, a station named
in ``alfen.toml``, the file's defaults, or mDNS discovery -- and
:func:`resolve_target` applies them in that order.  :func:`open_charger`
then connects and logs in, reporting on stderr rather than raising,
because every caller would only have printed the same thing.

``--station`` may also name several at once, which is
:func:`station_names`; what a command does with a list of them is
:mod:`alfenctl.cli.fanout`.
"""

from __future__ import annotations

import argparse
import sys

from devicectl.cli.target import first_set

from alfenctl.charger import DEFAULT_OLD_PASSWORD, DEFAULT_OLD_USER, AlfenCharger
from alfenctl.cli.output import error
from alfenctl.config import Config, StationConfig, load_config
from alfenctl.discovery import DEFAULT_HTTPS_PORT, Station, discover
from alfenctl.errors import AlfenError
from alfenctl.repo import RepoConfig

# What ``--station`` takes when it means every station at once.
ALL = "all"


def station_names(args: argparse.Namespace, config: Config) -> list[str]:
    """Return the stations ``--station`` named, or ``[]`` if it named none.

    ``all`` is every ``[stations.*]`` table in ``alfen.toml`` and nothing
    else.  Not what mDNS can see: a browse answers with whatever is on the
    network, which may include chargers belonging to somebody else, and "do
    this to every charger I can see" is a much larger promise than the one a
    person means when they type ``all``.

    One name comes back as a list of one, which is not a fan-out: a single
    station takes the path through :func:`open_charger` it always took.
    """
    raw = (args.station or "").strip()
    if not raw:
        return []
    if raw.lower() == ALL:
        if not config.stations:
            raise ValueError(
                f"--station all needs stations to name: {config.path or 'alfen.toml'} "
                "has no [stations.<name>] tables"
            )
        return list(config.stations)
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        raise ValueError(f"cannot read --station {args.station!r}")
    return names


def resolve_target(
    args: argparse.Namespace, config: Config, station_name: str | None = None
) -> tuple[Station | None, str, str]:
    """Resolve the station address and credentials for a command.

    Precedence: command line > ``[stations.<name>]`` table > top-level config
    defaults > mDNS discovery (by object id or IP) > the old-generation
    default credentials.

    ``station_name`` overrides ``--station``, for one station out of a list of
    them.  ``--host`` cannot: it is one address, and a list of stations is not.
    """
    wanted = first_set(station_name, args.station, default="")
    station_cfg: StationConfig | None = None
    if args.host and station_name is None:
        station = Station(
            ip=args.host,
            port=first_set(args.port, default=DEFAULT_HTTPS_PORT),
            https=not first_set(args.http, default=False),
        )
    elif wanted and (station_cfg := config.station(wanted)):
        station = Station(
            ip=station_cfg.host,
            port=first_set(args.port, station_cfg.port, default=DEFAULT_HTTPS_PORT),
            https=not first_set(args.http, station_cfg.http, default=False),
        )
    elif wanted:
        station = next(
            (
                st
                for st in discover(args.discover_time)
                if st.object_id.lower() == wanted.lower() or st.ip == wanted
            ),
            None,
        )
    elif config.host:
        station = Station(
            ip=config.host,
            port=first_set(config.port, default=DEFAULT_HTTPS_PORT),
            https=not first_set(config.http, default=False),
        )
    else:
        station = None
    return (
        station,
        first_set(
            args.username,
            station_cfg.username if station_cfg else None,
            config.username,
            default=DEFAULT_OLD_USER,
        ),
        first_set(
            args.password,
            station_cfg.password if station_cfg else None,
            config.password,
            default=DEFAULT_OLD_PASSWORD,
        ),
    )


def open_charger(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    login: bool = True,
) -> AlfenCharger | None:
    """Resolve, connect to and log into the target charger (or report why not).

    ``login=False`` returns a connected but unauthenticated client, for the
    password-recovery flow -- the point of which is that the password is
    not known.
    """
    config = load_config(args.config)
    try:
        station, username, password = resolve_target(args, config)
    except ValueError as exc:
        error(str(exc))
        return None
    if args.debug and config.path is not None and config.path.is_file():
        print(f"[debug] -- config: {config.path}", file=sys.stderr)
    if station is None:
        error(
            "no station selected; use --station <name|id|ip>, "
            "--host <ip>, or set one in alfen.toml (see --help)."
        )
        return None
    charger = AlfenCharger(station, username, password, debug=args.debug)
    if login:
        charger.login()
    return charger


def open_named(
    name: str, args: argparse.Namespace, config: Config, *, login: bool = True
) -> AlfenCharger:
    """Connect to one named station out of several, or say why it cannot be.

    Raises rather than reporting, unlike :func:`open_charger`: over several
    stations a failure is one section of the output, and the fan-out is what
    prints it under that station's heading and carries on to the next.
    """
    station, username, password = resolve_target(args, config, name)
    if station is None:
        raise AlfenError(
            f"no station named {name!r} in "
            f"{config.path or 'alfen.toml'}, and none answered to it on the network"
        )
    charger = AlfenCharger(station, username, password, debug=args.debug)
    if login:
        charger.login()
    return charger


def repo_config(args: argparse.Namespace) -> RepoConfig:
    """Return the firmware-server settings: Alfen's own, or the [firmware] table."""
    return load_config(args.config).firmware
