# Changelog

Notable changes, newest first. The version is set in
`src/alfenctl/__init__.py`; tagging `vX.Y.Z` publishes it (see
`.github/workflows/release.yml`).

## 0.1.0

First release. A tool for Alfen EV charging stations on the local network,
reimplemented from Alfen's own applications: discovery, the property catalog
and every read and write it allows, backup and restore, firmware upgrades
from a file or from Alfen's server, splash-screen logos, the event log,
charging sessions, RFID whitelists, passwords, licences, smart charging
networks, meter register maps and OCPP charging profiles -- as a command
line, and as `alfenctl ui`, a local web interface over the same code.

See the [README](README.md) and [docs](docs/) for what each of those does.
