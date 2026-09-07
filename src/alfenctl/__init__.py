"""A command-line tool for Alfen EV charging stations on the local network.

A small reimplementation of the useful core of Alfen's Windows "ACE Service
Installer" (reverse-engineered from v4.3.0 and verified against a live NG910
charger, firmware 7.4.5): discover chargers, inspect and change every
property, back up and restore configuration, upgrade firmware, and upload a
splash-screen logo -- all from the command line, no Alfen cloud involved.

The package is organised by concern:

* :mod:`alfenctl.discovery` -- mDNS browsing (:class:`Station`);
* :mod:`alfenctl.charger` -- the charger-local HTTP API client
  (:class:`AlfenCharger`), including the transport quirks the firmware upload
  needs;
* :mod:`alfenctl.eds` -- the bundled EDS property catalog (names, titles,
  types, enumerations for every known property);
* :mod:`alfenctl.values` -- merging live properties with the catalog, and
  value validation/coercion;
* :mod:`alfenctl.properties` -- resolving what the user asked for into
  properties, by id, by name, or by walking the charger;
* :mod:`alfenctl.firmware` -- firmware image parsing, release-file naming,
  version and compatibility rules, and the update-status vocabulary;
* :mod:`alfenctl.repo` -- Alfen's own firmware server: what it publishes,
  which of it fits a given charger, and fetching it;
* :mod:`alfenctl.upgrade` -- the end-to-end upgrade sequence, including
  picking a release when none was named;
* :mod:`alfenctl.logo` -- splash-screen logo conversion and packaging
  (.fwu for NG chargers, .tvf for AHP);
* :mod:`alfenctl.status` -- the live socket/meter/temperature view;
* :mod:`alfenctl.settings` -- the Windows app's XML settings/preset format;
* :mod:`alfenctl.whitelist` -- the local RFID authorization list;
* :mod:`alfenctl.transactions` -- the transaction database: charging
  sessions, meter values and OCPP events;
* :mod:`alfenctl.logs` -- the charger's event log: line parsing, the dated
  paged download, and probing how far back its buffer reaches;
* :mod:`alfenctl.errors` -- :class:`AlfenError`, the base of every failure
  this program reports rather than crashes on;
* :mod:`alfenctl.config` -- the optional ``alfen.toml`` configuration file;
* :mod:`alfenctl.progress` -- terminal progress rendering;
* :mod:`alfenctl.cli` -- the command-line interface: one module per
  group of commands, and a table that maps a typed word to a handler.
"""

from alfenctl.charger import AlfenCharger, ChargerInfo
from alfenctl.discovery import Station, discover
from alfenctl.errors import AlfenError
from alfenctl.firmware import (
    CompatResult,
    FirmwareFile,
    check_compatibility,
)
from alfenctl.repo import (
    Candidate,
    RemoteFirmware,
    RepoConfig,
    RepositoryError,
    candidates,
    list_firmware,
)

__version__ = "0.1.0"

__all__ = [
    "AlfenCharger",
    "AlfenError",
    "Candidate",
    "ChargerInfo",
    "CompatResult",
    "FirmwareFile",
    "RemoteFirmware",
    "RepoConfig",
    "RepositoryError",
    "Station",
    "__version__",
    "candidates",
    "check_compatibility",
    "discover",
    "list_firmware",
]
