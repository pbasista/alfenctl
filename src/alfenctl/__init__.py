"""A command-line tool for Alfen EV charging stations on the local network.

A small reimplementation of the useful core of Alfen's Windows "ACE Service
Installer" (reverse-engineered from v4.3.0 and verified against a live NG910
charger, firmware 7.4.5): discover chargers, inspect and change every
property, back up and restore configuration, upgrade firmware, and upload a
splash-screen logo -- all from the command line, no Alfen cloud involved.

The package is organised by concern:

* :mod:`alfenctl.discovery` -- mDNS browsing (:class:`Station`);
* :mod:`alfenctl.transport` -- one HTTP connection to one charger: the
  session, the retry, and the quirks the firmware upload needs;
* :mod:`alfenctl.charger` -- what that connection can be asked
  (:class:`AlfenCharger`), one method per endpoint;
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
* :mod:`alfenctl.config` -- the optional ``alfen.toml`` configuration file,
  and where firmware is fetched from;
* :mod:`alfenctl.cli` -- the command-line interface: one module per
  group of commands, and a table that maps a typed word to a handler.

What is not specific to a charger lives in ``devicectl-core`` and is shared
with the other programs of this shape: the progress protocol
(:mod:`devicectl.report`, :mod:`devicectl.progress`), the subcommand table
(:mod:`devicectl.cli.command`), the event broadcaster
(:mod:`devicectl.web.events`) and the HTTP primitives
(:mod:`devicectl.web.http`).
"""

from typing import Any

__version__ = "0.2.0"

# Which module each published name lives in, looked up the first time it is
# asked for.  Importing them here instead -- which is what this file used to
# do -- made every invocation pay for the lot: `alfenctl --version` built an
# HTTP client, an mDNS browser, an FTP client and a zip reader, 120 ms of
# them, to print a string.  PEP 562 keeps the package's published surface
# exactly as it was and imports nothing until something reaches for it.
_EXPORTS = {
    "AlfenCharger": "alfenctl.charger",
    "ChargerInfo": "alfenctl.charger",
    "Station": "alfenctl.discovery",
    "discover": "alfenctl.discovery",
    "AlfenError": "alfenctl.errors",
    "CompatResult": "alfenctl.firmware",
    "FirmwareFile": "alfenctl.firmware",
    "check_compatibility": "alfenctl.firmware",
    "RepoConfig": "alfenctl.config",
    "Candidate": "alfenctl.repo",
    "RemoteFirmware": "alfenctl.repo",
    "RepositoryError": "alfenctl.repo",
    "candidates": "alfenctl.repo",
    "list_firmware": "alfenctl.repo",
}

__all__ = ["__version__", *sorted(_EXPORTS)]


def __getattr__(name: str) -> Any:
    """Import the module a published name lives in, the first time it is used."""
    import importlib

    where = _EXPORTS.get(name)
    if where is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(where), name)
    globals()[name] = value  # so the next reach for it is a plain lookup
    return value


def __dir__() -> list[str]:
    """List what this package publishes, imported or not."""
    return sorted(__all__)
