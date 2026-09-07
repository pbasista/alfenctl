# Reference

The options every command takes, what the exit codes mean, and the
things worth knowing before trusting the tool with a charger.

## Options
Every station command accepts:

| Option | Meaning |
| --- | --- |
| `--station NAME` | station name from `alfen.toml`, its Object ID (serial), or its IP (via mDNS) |
| `--host IP`, `--port N`, `--http` | target a charger directly instead of mDNS (`--http` for pre-5.0 chargers) |
| `-u`, `-p` | charger login credentials (default: the old-generation `cpadmin` / `L@0Pa$$`) |
| `--config FILE` | settings file (default: the path `alfenctl config path` prints) |
| `--discover-time S` | seconds to browse for stations (default 4) |
| `--debug` | log every HTTP request/response to stderr |

`ui` takes `--listen ADDR` (a port, a host, or `HOST:PORT`; default
`127.0.0.1:8088`), `--read-only`, `--token`/`--no-token`, `--allow-host NAME`,
`--no-browser`, `--poll-interval S` and `--idle-timeout S`.

`firmware`, `import`, `logo`, `export`, `log`, `transactions`, `reboot`,
`cmd` and `erase` additionally take
`-y/--yes` (no prompt — for `export`/`log`, overwrite an existing output
file without asking); `firmware` takes `--new-password` (the 5.0 boundary),
`--install-timeout S` and, when no file is named, `--list`, `--all` and
`--cache-dir DIR`; `import` takes `--dry-run`; `log` takes
`--since WHEN`/`--all`/`--range`/`-n N`/`-g REGEX`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | error: station not found, communication error, invalid input, upload rejected, or a prompt declined |
| 2 | firmware file failed the compatibility checks |
| 3 | another upload is already in progress on the charger |
| 4 | upload was sent, but the install did not reach a good terminal state |
| 5 | Alfen's server offered nothing for this charger, or could not be reached |
| 130 | interrupted by Ctrl+C |


## Notes and limitations

* The charger reads the firmware/logo upload at only ~30–40 KB/s, so a
  ~1.8 MB image takes about a minute to transfer. That is the device, not
  this tool.
* Alfen's firmware server speaks plain FTP, as the Windows app uses it, so
  the listing and the download are unencrypted. The credentials are the
  shared installer account published in the app's binary, not yours.
* Server certificate validation is intentionally disabled: the chargers
  ship self-signed certificates, exactly as the Windows app also bypasses
  it.
* Compatibility checks are advisory — the charger enforces the real rules
  (family, signature, container integrity) server-side.
* Interrupting during an upload is safe: nothing is flashed until the
  complete image has been accepted.
* `cmd` is the charger's own console, unvalidated: it accepts anything and
  reports what it did only in its event log, so `cmd` prints no result of
  its own. `cmd --list` prints everything the three reverse-engineered
  sources record about it: the Windows app sends five commands (`reboot`,
  `txerase`, `date <timestamp>`, `eepromx erase config` and
  `forcefirmwarepermanent`), a real NG910 log shows a sixth (`cansync off`)
  that appears in no app, and My Eve names nineteen more without ever
  recording the string behind them. A blank command column therefore means
  unknown, not unavailable — and `reboot`/`erase` wrap the useful ones.
* `erase settings` returns the charger to factory defaults *including its
  network configuration*, so you can lose contact with it; it takes effect
  on the next reboot.
* While the charger is rebooting it does not refuse connections, it simply
  stops answering, so each poll blocks until it times out. Polls therefore
  run with a short timeout of their own and on a background thread, so the
  progress line keeps counting rather than freezing on the request. The
  session does not survive the reboot (it is bound to the TCP connection),
  so the first poll the charger *does* answer comes back 401 and is
  re-authenticated and retried on that same short budget.
* Log timestamps can jump backwards around a restart: the charger boots
  with its clock at the firmware build date and only jumps forward once
  NTP or a `date` command sets it. Ordering therefore follows the record
  id, which is monotonic, and `--since` stops paging only once a whole page
  predates the cutoff — one stale line cannot cut an export short. Lines
  that do carry a stale timestamp are still filtered out by `--since`.
* The `--since` cutoff is applied to the lines, but the charger pages the
  log in fixed-size blocks, so the block the cutoff falls inside is
  downloaded whole and then trimmed. That is the "dropped N fetched lines"
  note; nothing you asked for is missing.
* `import` skips **device-bound** properties by default: serial number,
  charge-box identity, Ethernet MAC, IP configuration, SCN membership,
  SIM pin, license key and the energy-meter/Modbus wiring. They are
  writable, but they describe *the charger the dump came from*, so
  restoring them onto a second device misidentifies it (or strands it, in
  the case of the IP). This is the app's own list
  (`PropertyStorage.s_forbiddenProperties`), which it applies by leaving
  them out of its settings files; `export` keeps them, since a dump is
  also a record of how a charger was set up, and `import --force` writes
  them.
* `set`/`import` refuse read-only properties and out-of-range values before
  anything is sent; a few exotic properties unknown to both the charger's
  metadata and the EDS pass through unvalidated, and the charger remains
  the final authority.
* On top of the type check, `set` carries My Eve's own bounds for the 64
  writable properties the app validates. Those are **warnings**, not
  refusals: the phone app's limits are the ordinary ones — it caps a socket
  at 32 A, which is right until the station is licensed for high-power
  sockets — and `set` is the escape hatch for what the curated commands
  will not do.
* Thirteen properties are accepted, answered 200, and then ignored until
  the station restarts (My Eve's `propertiesWhenChangedNeedCSReboot`).
  `set`, `import`, `auth set` and `ocpp set` say which of their writes are
  waiting on one.
* Backoffice presets are not settings documents. Alfen publishes ~930 of
  them as signed `.fwi` blobs, so `preset <name>` clears the current
  backoffice properties, pushes the blob through `POST /api/firmware`,
  writes the preset's name into `0x2076_0` and asks for a reboot — the
  same sequence as `PanelConnectivity.OnSaveChanges`. Each is published
  once per encryption key (`-A`/`-B`); the charger's firmware version picks
  the copy it can decrypt.
* Nothing can read a `secret` back — not this tool, not the app, not the
  charger's own API. Installing one is therefore unverifiable from here:
  the charger answers HTTP 200 to a well-formed request whether or not the
  value is the one your backoffice expects.
* Not implemented from the Windows app, on purpose: everything that goes
  through Alfen's own service back end rather than the charger — updating a
  license key from their server, assigning an object id, loading settings
  from ISAH — since all of it needs an Alfen service account, and the app's
  own updater. The SCN live roster (a UDP broadcast every member sends) is
  a separate deliberate choice, explained in
  [how-it-works.md](how-it-works.md). Also skipped: reordering
  SCN members by socket id (the app swaps two stations' ids to change load
  balancing priority) and per-station phase mapping — both reachable today
  with `get`/`set` on `2180_2` and `2180_7`/`2180_9`, but not wrapped in a
  command. The four OCPP network profiles (`0x20F0`–`0x20F3`) are likewise
  left to `get`/`set`: they are a panel of their own, and clearing one is
  not what "change the backoffice URL" asked for.

