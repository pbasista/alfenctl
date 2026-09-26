# Changelog

Notable changes, newest first. The version is set in
`src/alfenctl/__init__.py`; tagging `vX.Y.Z` publishes it (see
`.github/workflows/release.yml`).

## 0.2.0 — 2026-09-26

The first release published to PyPI, and the next after the pre-publication
`0.1.0` below. It requires `devicectl-core>=0.1.0`.

- **Built on the shared core.** The web interface was rebuilt on the
  `devicectl-core` design system and widget library, so it is the same page as
  jkctl's in a different colour: a Fleet tab of station tiles, a page-wide
  draft store with **Apply** and **Discard** in the header, cards whose own
  tick and cross apply just their edits, the shared power chart with the
  temperature drawn on it, draggable alarm and temperature limit bands, the
  health card, the live watcher list, and one drawn wordmark and bell.
- **Three pieces moved into core.** The doctor findings, the `--listen`
  address parser and the per-user config directory were written out here and,
  identically, in jkctl; they are `devicectl.doctor.finding_json`,
  `devicectl.web.server.parse_listen` and `devicectl.paths.config_dir` now.
- **Manufacturer cloud from the UI.** Sign in without pasting a token, read a
  station's registered information and licence from Alfen, with automatic
  loopback sign-in and a sign-out.
- **Reads across the fleet.** A read can be asked of several stations at once,
  turning `--json` into one document keyed by station.
- **Safer I/O.** Nothing is overwritten without being asked, and `-` means the
  standard stream wherever a file is expected.
- **The web interface is the default.** `alfenctl` with no command serves the
  page; the header says what this build is and links to it.

## 0.1.0

First release. A tool for Alfen EV charging stations on the local network,
reimplemented from Alfen's own applications: discovery, the property catalog
and every read and write it allows, backup and restore, firmware upgrades
from a file or from Alfen's server, splash-screen logos, the event log,
charging sessions, RFID whitelists, passwords, licences, smart charging
networks, meter register maps and OCPP charging profiles -- as a command
line, and as `alfenctl ui`, a local web interface over the same code.

See the [README](README.md) and [docs](docs/) for what each of those does.
