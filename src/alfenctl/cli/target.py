"""Which charger a command talks to, and as whom.

The answer can come from four places -- the command line, a station named
in ``alfen.toml``, the file's defaults, or mDNS discovery -- and
:func:`resolve_target` applies them in that order.  :func:`open_charger`
then connects and logs in, reporting on stderr rather than raising,
because every caller would only have printed the same thing.
"""

from __future__ import annotations

import argparse
import sys
from typing import TypeVar

from alfenctl.charger import DEFAULT_OLD_PASSWORD, DEFAULT_OLD_USER, AlfenCharger
from alfenctl.config import Config, StationConfig, load_config
from alfenctl.discovery import DEFAULT_HTTPS_PORT, Station, discover
from alfenctl.repo import RepoConfig


T = TypeVar("T")


def first_set(*values: T | None, default: T) -> T:
    """Return the first value that was actually given, else ``default``.

    Sources are passed most specific first, so a precedence rule reads as
    one line instead of a stack of conditionals.
    """
    return next((value for value in values if value is not None), default)


def resolve_target(
    args: argparse.Namespace, config: Config
) -> tuple[Station | None, str, str]:
    """Resolve the station address and credentials for a command.

    Precedence: command line > ``[stations.<name>]`` table > top-level config
    defaults > mDNS discovery (by object id or IP) > the old-generation
    default credentials.
    """
    station_cfg: StationConfig | None = None
    if args.host:
        station = Station(
            ip=args.host,
            port=first_set(args.port, default=DEFAULT_HTTPS_PORT),
            https=not first_set(args.http, default=False),
        )
    elif args.station and (station_cfg := config.station(args.station)):
        station = Station(
            ip=station_cfg.host,
            port=first_set(args.port, station_cfg.port, default=DEFAULT_HTTPS_PORT),
            https=not first_set(args.http, station_cfg.http, default=False),
        )
    elif args.station:
        station = next(
            (
                st
                for st in discover(args.discover_time)
                if st.object_id.lower() == args.station.lower() or st.ip == args.station
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
        print(f"error: {exc}", file=sys.stderr)
        return None
    if args.debug and config.path is not None and config.path.is_file():
        print(f"[debug] -- config: {config.path}", file=sys.stderr)
    if station is None:
        print(
            "error: no station selected; use --station <name|id|ip>, "
            "--host <ip>, or set one in alfen.toml (see --help).",
            file=sys.stderr,
        )
        return None
    charger = AlfenCharger(station, username, password, debug=args.debug)
    if login:
        charger.login()
    return charger


def repo_config(args: argparse.Namespace) -> RepoConfig:
    """Return the firmware-server settings: Alfen's own, or the [firmware] table."""
    return load_config(args.config).firmware
