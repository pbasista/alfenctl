# Reference

The options every command takes, what the exit codes mean, and the
things worth knowing before trusting the tool with a charger.

## Options
Every station command accepts:

| Option | Meaning |
| --- | --- |
| `--station NAME` | station name from `alfen.toml`, its Object ID (serial), or its IP (via mDNS). A comma-separated list, or `all` for every station in `alfen.toml`, runs a **read** over each (see below) |
| `--host IP`, `--port N`, `--http` | target a charger directly instead of mDNS (`--http` for pre-5.0 chargers) |
| `-u`, `-p` | charger login credentials (default: the old-generation `cpadmin` / `L@0Pa$$`) |
| `--config FILE` | settings file (default: the path `alfenctl config path` prints) |
| `--discover-time S` | seconds to browse for stations (default 4) |
| `--debug` | log every HTTP request/response to stderr |

### Several stations at once

The commands that only read take a list: `status`, `info`, `doctor`,
`props`/`ls`, `get`, `connectivity`, and the `show`/`list`/`status` action of
`auth`, `ocpp`, `loadbalancing`, `current`, `brightness`, `socket`,
`license`, `time`, `scn`, `tags`, `meter-map`, `charging-profiles` and
`direct-start`.

One station prints exactly as it always did. Several get a `=== name ===`
heading each, and `--json` comes back as one object keyed by station name
rather than several documents in a row. They are read sequentially, each in
its own session; a station that does not answer is reported under its own
heading and the rest are still read, with the exit code of the first
failure.

`all` means the stations `alfen.toml` names, and not whatever mDNS can see
-- a browse finds chargers that may not be yours. `--host` names one
address, so `--host` with a list of stations is an error rather than a
guess.

A command that writes takes one station at a time: each of them wants its
own preview and its own confirmation.

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
* `cmd` submits free-form text to the charger's console. `cmd --list` and
  the web console share a catalog of command strings documented in vendor
  clients and an NG910 log, including `flash-info` and `flash-dump`.
  MyEve limits advanced choices to the station's Secure Service Access
  (SSA) login role, which is separate from owner/admin access. In reported
  NG910-60027 operation, these two flash commands produced no observable
  action or log output. Command availability and authorization depend on
  the installed firmware. HTTP success acknowledges submission rather than
  execution; inspect the log for command output. Dumps may contain sensitive
  data, and erase, test, reset, and tamper commands can disrupt charging or
  configuration.
* `diag send` submits a firmware-specific diagnostic through `/api/diagtool`
  after confirmation (`-y` skips the prompt). `diag result` reads the current
  result once and prints the response JSON. Match its command and sequence
  ID and inspect its finished flag: it may describe an earlier request or
  an operation still in progress. The inspected clients define the transport
  without a diagnostic command catalog; command names, parameters, and result
  formats depend on the firmware.
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
* `cloud` reaches Alfen's own servers rather than the charger, to read what
  they hold about a station (account, warranty, how many changes Alfen has
  logged for it, the license key on file, and — with `cloud info --defaults`
  — the full factory-default property profile, which is every property value
  the manufacturer keeps for the station) and — on `cloud license --install`
  — to write that key to the charger. It
  follows the **My Eve** mobile back end, because that is the account an owner
  has: it signs in through Alfen's Azure AD B2C tenant, which yields a bearer
  token, then calls one GraphQL endpoint. There is no username/password
  (ROPC) grant, so alfenctl never handles the Alfen password: `cloud login`
  opens Alfen's own login page in a browser and catches the resulting code on
  a one-shot local loopback server (the client registers a `localhost`
  redirect and B2C accepts it on any port), so it finishes on its own with
  nothing to paste, or you supply a token with `--token`/`$ALFEN_CLOUD_TOKEN`.
  `cloud logout` forgets the cached token, so a different account can sign in.
  The manufacturer holds nothing else about a station: the `getLocation*`
  operations in the app are geocoding helpers that turn an address the user
  types into coordinates, not station data, so they are not wrapped. The live
  token exchange and GraphQL calls are the one part not exercised by the test
  suite (which drives them through a mock), and the operation/field names are
  reconstructed from the decompiled app; if Alfen has changed them, a query
  may need adjusting. This is the piece of the vendors' service back end
  worth having; the rest is still left out on purpose — assigning an object
  id and loading settings from **ISAH** need the Windows installer's own
  service account, not a My Eve one. The SCN live roster (a UDP broadcast every member sends) is
  a separate deliberate choice, explained in
  [how-it-works.md](how-it-works.md). Also skipped: reordering
  SCN members by socket id (the app swaps two stations' ids to change load
  balancing priority) and per-station phase mapping — both reachable today
  with `get`/`set` on `2180_2` and `2180_7`/`2180_9`, but not wrapped in a
  command. The four OCPP network profiles (`0x20F0`–`0x20F3`) are likewise
  left to `get`/`set`: they are a panel of their own, and clearing one is
  not what "change the backoffice URL" asked for.

