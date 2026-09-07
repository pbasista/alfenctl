"""Optional TOML configuration for station addresses and credentials.

So credentials don't have to be retyped on every invocation, the CLI reads
``alfen.toml`` (override with ``--config``).  Top-level keys are defaults;
``[stations.<name>]`` tables override them per station, and ``--station
<name>`` picks a table by name (a name that matches no table still resolves
via mDNS, as before).  Command-line flags override everything.

See :data:`EXAMPLE_CONFIG` below for the file ``alfenctl config init``
writes, which doubles as the reference for what may appear in one.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alfenctl.repo import RepoConfig

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10, via the tomli dependency
    import tomli as tomllib

# Where the file lives when --config is not given; see default_config_path.
CONFIG_DIR_NAME = "alfen"
CONFIG_FILE_NAME = "alfen.toml"

# What ``alfenctl config init`` writes.  It is a working file, all of it
# commented out, so an installer can uncomment the two lines they need
# instead of getting the syntax wrong in an empty file.
EXAMPLE_CONFIG = """\
# alfenctl configuration.  Every setting is optional, and a command-line
# flag beats anything written here.  Full reference: `alfenctl --help`.

# Credentials for every station, unless a station below overrides them.
# username = "admin"
# password = "changeme"

# A station gets a name here, and `--station garage` then finds it.
# Without a name, --station still takes a charger's Object ID (the serial
# printed on it) or its IP, which alfenctl resolves over mDNS.
# [stations.garage]
# host = "192.168.11.42"

# A pre-5.0 charger speaks plain HTTP on a different account.
# [stations.old]
# host = "192.168.11.43"
# http = true
# username = "cpadmin"
# password = "..."

# Where `alfenctl firmware` looks for images.  The default is Alfen's own
# server, with the credentials their Windows installer ships; set this only
# to point at a mirror of your own.
# [firmware]
# site = "ftp.example.com"
# username = "installer"
# password = "..."
# directory = "Firmware"
"""

# Keys accepted in the file, per station table and (minus host/port/https) at
# the top level.  Unknown keys are rejected so typos don't silently no-op.
_TOP_KEYS = frozenset(
    {"username", "password", "host", "port", "http", "stations", "firmware"}
)
_STATION_KEYS = frozenset({"host", "port", "http", "username", "password"})
# Keys accepted in the [firmware] table: where to fetch firmware images from.
_FIRMWARE_KEYS = frozenset(
    {"site", "port", "username", "password", "directory", "timeout"}
)


def default_config_dir() -> Path:
    """Return the directory the configuration lives in, per platform.

    ``XDG_CONFIG_HOME`` wins wherever it is set, so a dotfiles setup that
    exports it keeps working.  Otherwise Windows uses ``%APPDATA%``, where
    Windows programs keep per-user settings; everywhere else uses
    ``~/.config``, which is both the XDG default and where command-line
    tools put themselves on macOS.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / CONFIG_DIR_NAME
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / CONFIG_DIR_NAME
    return Path.home() / ".config" / CONFIG_DIR_NAME


def default_config_path() -> Path:
    """Return the configuration file used when ``--config`` is not given."""
    return default_config_dir() / CONFIG_FILE_NAME


@dataclass
class StationConfig:
    """One ``[stations.<name>]`` table: an address plus optional overrides."""

    name: str
    host: str  # always set: _parse_station rejects a table without one
    port: int | None = None
    http: bool | None = None
    username: str | None = None
    password: str | None = None


@dataclass
class Config:
    """The parsed configuration: defaults plus named stations."""

    path: Path | None = None
    username: str | None = None
    password: str | None = None
    host: str | None = None
    port: int | None = None
    http: bool | None = None
    stations: dict[str, StationConfig] = field(default_factory=dict)
    firmware: RepoConfig = field(default_factory=RepoConfig)

    def station(self, name: str) -> StationConfig | None:
        """Return the station table for ``name`` (case-insensitive), or None."""
        exact = self.stations.get(name)
        if exact is not None:
            return exact
        lowered = name.lower()
        for key, st in self.stations.items():
            if key.lower() == lowered:
                return st
        return None


def _validate_keys(table: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    """Reject unknown keys so a typo can't silently be ignored."""
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ValueError(f"unknown key(s) in {where}: {', '.join(unknown)}")


def _parse_station(name: str, table: dict[str, Any]) -> StationConfig:
    """Validate and convert one ``[stations.<name>]`` TOML table."""
    _validate_keys(table, _STATION_KEYS, f"[stations.{name}]")
    host = table.get("host")
    port = table.get("port")
    http = table.get("http")
    if not isinstance(host, str) or not host:
        raise ValueError(f"[stations.{name}] must set 'host' to an address")
    if port is not None and not isinstance(port, int):
        raise ValueError(f"[stations.{name}] 'port' must be an integer")
    if http is not None and not isinstance(http, bool):
        raise ValueError(f"[stations.{name}] 'http' must be a boolean")
    return StationConfig(
        name=name,
        host=host,
        port=port,
        http=http,
        username=table.get("username"),
        password=table.get("password"),
    )


def _parse_firmware(table: dict[str, Any]) -> RepoConfig:
    """Validate the ``[firmware]`` table, filling in Alfen's own server as default."""
    _validate_keys(table, _FIRMWARE_KEYS, "[firmware]")
    repo = RepoConfig()
    for key in ("site", "username", "password", "directory"):
        value = table.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"[firmware] '{key}' must be a string")
            setattr(repo, key, value)
    port = table.get("port")
    if port is not None:
        if not isinstance(port, int):
            raise ValueError("[firmware] 'port' must be an integer")
        repo.port = port
    timeout = table.get("timeout")
    if timeout is not None:
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
            raise ValueError("[firmware] 'timeout' must be a number")
        repo.timeout = float(timeout)
    return repo


def load_config(path: Path | None = None) -> Config:
    """Load the configuration; a missing file yields an empty :class:`Config`.

    Raises ``ValueError`` on malformed content (bad keys, wrong types), and
    lets ``tomllib``'s own error propagate for broken TOML syntax.
    """
    if path is None:
        path = default_config_path()
    if not path.is_file():
        return Config(path=path)
    data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    _validate_keys(data, _TOP_KEYS, str(path))
    stations: dict[str, StationConfig] = {}
    raw_stations = data.get("stations", {})
    if not isinstance(raw_stations, dict):
        raise ValueError("'stations' must be a table of tables")
    for name, table in raw_stations.items():
        if not isinstance(table, dict):
            raise ValueError(f"[stations.{name}] must be a table")
        stations[name] = _parse_station(name, table)
    raw_firmware = data.get("firmware", {})
    if not isinstance(raw_firmware, dict):
        raise ValueError("'firmware' must be a table")
    return Config(
        path=path,
        username=data.get("username"),
        password=data.get("password"),
        host=data.get("host"),
        port=data.get("port"),
        http=data.get("http"),
        stations=stations,
        firmware=_parse_firmware(raw_firmware),
    )
