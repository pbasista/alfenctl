# Reverse-engineering the alfen_wallbox Home Assistant integration

The [leeyuentuen/alfen_wallbox](https://github.com/leeyuentuen/alfen_wallbox)
integration is the most complete public HTTP-API client for Alfen chargers
besides the vendor's own apps — a fork chain of
`sockless-coding/garo_wallbox` → `egnerfl/alfen_wallbox` →
`leeyuentuen/alfen_wallbox`. Two notes from the search for it, so nobody
repeats it: the task-named repos `hromi/alfen-wallbox` and
`MBA-informatica/alfen-wallbox` do **not** exist (HTTP 404, verified via
the GitHub API), and `leeyuentuen/alfen_wallbox` (underscore) is the
canonical active one.

What makes it valuable is its **wiki page `API-paramID`**, which reproduces
the charger's own `OD_*` object-dictionary names for a few hundred property
ids — a source the vendor publishes nowhere else — plus working entity
definitions and a proven HTTP client. The result of mining it is
[`ha-findings.md`](ha-findings.md).

## Step 1 — Clone the repo and the wiki

Wikis are separate git repositories:

```console
$ git clone https://github.com/leeyuentuen/alfen_wallbox alfen-wallbox
$ git clone https://github.com/leeyuentuen/alfen_wallbox.wiki alfen-wallbox.wiki
```

## Step 2 — Read the HTTP client

`custom_components/alfen_wallbox/alfen.py` is the API client, and it proves
every mechanic this project also needed:

* `POST /api/login` with `{username, password, displayname}`; session
  auth, one connection at a time.
* `GET /api/prop?cat=<category>&offset=<N>` — paginated per category;
  `GET /api/prop?ids=<comma list>` for explicit ids.
* `POST /api/prop` with body `{"2129_0": {"id": "2129_0", "value": 16}}`
  (values are sent as `str(value)`).
* `POST /api/cmd` with `{"command": "reboot"}` / `"txerase"`.
* The category list lives in `const.py` (comm, generic, generic2, MbusTCP,
  meter1..4, ocpp, states, temp, …).

## Step 3 — Mine the wiki parameter dictionary

`API-paramID.md` is a table of `paramID | OD_name | description`, with
subIds zero-padded to 2 hex digits (`2051_00`, `2180_0A` — normalize when
comparing). The `OD_*` names are the authoritative vendor object-dictionary
names; the findings cite them as `wiki:N`.

## Step 4 — Mine the entity definitions

Every platform file under `custom_components/alfen_wallbox/` names the
properties it reads or writes, with units, ranges and enums:

* `sensor.py` — read-only telemetry (meters, states, identity, per-phase
  values), plus the big `*_DICT` enum maps (status, main state, power
  state, mode 3, display errors).
* `number.py` / `select.py` / `switch.py` / `text.py` / `binary_sensor.py`
  — the writable ones, with their min/max/step and option dicts; every
  entry here is proof that a property accepts a `POST`.
* `const.py` — the license bitmap (`21A2_0`) and category list.

Record each id with the file:line as evidence. Watch for the repo's own
mislabels and carry the doubt into the confidence column — e.g. it swaps
`2203/2204` (alarm-high vs check-interval) against the wiki, and reads
`2064_0` / `2174_0` where the wiki lists per-sub entries.

## Step 5 — Corroborate

Cross-check against the live charger and the other two sources: the wiki's
`OD_*` name usually agrees with the Windows installer's `EDS.xml`, and the
entity ranges with My Eve's validation rules. Where only this repo knows an
id, say so — its sensor names are sometimes wrong about units (kW vs W on
`3221_13..16`, ms vs s on `2060_0`) even when the id itself is right.

Everything extracted this way is in [`ha-findings.md`](ha-findings.md): the
property table with per-row evidence, the enum maps, units, multi-sub
object layouts, and the read-only/writable lists.
