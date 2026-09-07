# How it works

What alfenctl talks to, and what it learned from the vendor's own
installer. See the [README](../README.md) for how to use it.

* **Discovery** is mDNS-based, like the app: `_alfen._tcp` (new generation,
  v5+ / AHP, HTTPS) and `_lolo3._http._tcp` (old generation, NG9xx < 5.0,
  HTTP).
* **Everything else** talks to the charger's local HTTP API at
  `https://<ip>:443/api/<command>` (JSON). The session is bound to the TCP
  connection, and the charger serves only one connection at a time. Its TLS
  certificate is self-signed, so verification is disabled (as the app does).
* **Properties**: the charger reports each property's value plus metadata
  (`type`, `access`, `len`, `cat`) through `GET /api/prop`, paged by
  category (`GET /api/categories`); names, titles, units and enumerations
  come from the app's bundled CANopen-style **EDS** catalog (`EDS.xml`,
  shipped with this package, 686 objects), merged onto the live values.
  Writes are `POST /api/prop` in batches of 15, byte-encoded exactly like
  the app's `StoreProperties` (strings quoted, reals/integers raw JSON
  numbers, byte arrays as comma-joined hex).
* **Firmware sources** mirror the app's `UpdateManager`: Alfen publishes
  its images on `ftp.alfen.com` under `Firmware/`, reachable with the shared
  installer credentials the app ships in its binary
  (`AppProperties.FTPSite`/`FTPUsername`/`FTPPassword`). The app mirrors that
  folder to `%APPDATA%` on startup and its upload dialog lists the mirror
  filtered by file extension alone; `alfenctl` lists the server on demand and
  filters harder (see below).
* **Firmware upgrade** mirrors the app's `StartUpload`: compatibility
  checks, clock set (signature validation depends on it), a single-part
  streamed multipart POST to `/api/firmware` in ~7 KB TLS records with
  `Accept: */*` (each detail isolated on real hardware), polling through the
  charger's self-triggered reboot, then `forcefirmwarepermanent`.
* **Event log**: `GET /api/log?offset=N` returns one page of the charger's
  flash ring buffer, counted in lines back from the newest, oldest-first
  within the page (the app's `GetLogLines`). Reversing the page order gives
  a chronological log, which is what the app writes to file. `--since`
  mirrors what the app's save dialog does with its 1/3/7/21-day buttons
  (`ICULanLog.SaveToFile` takes a `TimeSpan`) — it just takes any date
  rather than four fixed ones. **Nothing in the API reports how far back
  the log reaches**: there is no call for it, no EDS property, no OCPP
  configuration key, and the app never asks — it discovers the end by
  running into it. `--range` recovers the answer by bisecting `offset`
  instead, using the record ids (monotonic, 128 bytes apart) to tell a real
  page from the end of the buffer.
* **Write-only items** (keys and certificates) never touch `/api/prop` at
  all: the charger keeps them behind `POST /api/domain`, addressed by an
  item-type number rather than a property id, with the value hex-encoded
  (`ICUDomain`). See *Write-only secrets* below.
* **Live state** sits at `(0x2501, n)` for socket 1 and `(0x2502, n)` for
  socket 2 (`PanelMonitoring`): sub-index 1 is the main state
  (`EMainStates`), 2 the LED state, 3 the relay/power state and 4 the
  IEC 61851 Mode-3 pilot state (`EMode3States`, where `160` is *A, no
  vehicle* and `194` is *C2, charging*). The decoding is checked against a
  real NG910-60027 export in the test suite.
* **Settings files**: the app's `<Settings>` XML (`PropertyStorage`), whose
  `<Property Id="2050_00" Value="…" />` ids are spelled `%04X_%02X` — padded,
  unlike the `2050_0` the charger's own API uses. alfenctl writes the app's
  spelling and reads either. The app applies the device-bound property
  filter in *both* directions; alfenctl keeps those in an export and filters
  on import.
* **Presets** live beside the firmware on `ftp.alfen.com`, in `TCPPresets/`,
  `RTUPresets/` and `BackofficePresets/` — the folders the app mirrors to
  `%APPDATA%` on startup — as plain settings XML.
* **Whitelist**: `GET /api/whitelist?index=N` returns a page of tags, and
  the same endpoint takes the verbs `?add=`, `?remove=`, `?clear` and
  `?starttagaddmode`; `POST /api/addtag` writes a whole record. The list
  is **sparse**, so an empty page is not the end of it: the app steps the
  index on in 16-tag strides (15 below firmware 3.4.0) through up to 128
  empty slots before it accepts that the list has ended
  (`ICUWhiteList.DoWorkRead`), and so does `alfenctl`.
* **Master tag**: one RFID tag that always authorises, independent of the
  whitelist — a mode flag and the tag id, at properties `2400_1`/`2400_2`
  (`ICUMasterTag`). Like the license properties, neither appears in the
  category walk or the EDS catalog, so `tags master` reads and writes them
  by explicit `ids=` query rather than through the normal `get`/`set`
  machinery.
* **Wi-Fi scan**: `GET /api/wifiscan` asks the charger's own radio what
  networks it can currently see (`ICULanDevice.ExecutedWifiScan`), answered
  as `{"scan_results": [{"Ssid", "SignalStrength", "Security", "Band"}]}`.
  The SSID, passphrase and security type themselves
  (`wifiSSID`/`wifiPSK`/`wifiSecurity`) are ordinary EDS properties, already
  reachable with `get`/`set`; `wifi` adds the discovery step the app's *Scan
  Wi-Fi networks* button provides, decoding the security type with the
  labels `SupportedWifiSecurityType` carries but the EDS does not.
* **Smart-meter test**: `meter-test` reads six live measurands — per-phase
  current and active power — at `(0x5221, n)`, a live-only object with no
  EDS entry, populated once the `meter4` category has been read. This is
  the app's Modbus TCP/RTU "Test" dialog, used during commissioning to
  confirm an external kWh meter's wiring and CT orientation before trusting
  it for load balancing.
* **OCPP charging profiles**: `GET/POST /api/chargingprofiles` manages
  charge-schedule objects the charger enforces locally
  (`ICUChargingProfiles`) — `?id_list` to enumerate, `?cpid=N` to read one,
  `?clear=N`/`?clear=all` to remove, `?add=` (POST, JSON body) to install
  one. The app's own UI only ever installs one such profile: the default
  weekly schedule required by the UK's Electric Vehicles (Smart Charging)
  Regulations 2021, identified by the fixed id `-19061964`
  (`s_idUKSmartCharging`). `charging-profiles install-uk` reproduces it
  exactly — Monday-Friday, charging blocked 08:00-11:00 and 16:00-22:00,
  allowed the rest of the time (including weekends), with the
  regulation's randomised-start-delay flag set — verified field-for-field
  against `AddUkSmartChargingProfile` in the test suite. `list`/`show`/
  `clear` work on any profile, not just that one.
* **Smart Charging Network (SCN)**: a group of chargers sharing one grid
  connection's current budget. One charger's own membership lives at
  properties `2180_1`..`2180_10` — network name, this charger's socket id,
  the group's total socket count, and the shared current/timing settings —
  absent from the EDS catalog like the license properties, so read by
  explicit `ids=` query. The app finds a network's *other* members through
  a live UDP broadcast (`SCNNetwork`, port 36549, AES-encrypted status
  packets) so it can compute a free socket id without every member's
  password up front; `alfenctl` has no such broadcast to listen for, so
  `scn join`/`leave` instead mDNS-discover the LAN and log into every
  charger found with the target's own credentials, reading each one's
  `2180_1` to see who else is in the named network. One simplification
  from the app: given a gap in the id sequence left by a removed member,
  the app reuses it (`FindAvailableSocketId`); `alfenctl` always appends
  past the highest id in use and never renumbers an existing member's id
  — see `alfenctl.scn`'s module docstring for why.
* **Eve Connect app PIN**: `password pin` sets, or `--disable`s, a second
  independent credential — a 4-6 digit PIN gating the Eve Connect mobile
  app's access to the charger, distinct from the admin login password.
  Same `POST /api/password` endpoint as `password set`, but with
  `username: "end user"` (`ICULanDevice.SetEndUserPin`/
  `DisableEndUserAccess`); `--allow-empty` enables access without
  requiring a PIN at all.
* **Transactions**: `GET /api/transactions?offset=N` pages *backwards*
  through a record buffer, starting at `offset=0xFFFFFFFF` and asking
  again with the offset of the last record received
  (`ICUTransactions.Read`). Records are `<offset>_<text>` lines in one of
  nine prefixed grammars — `tx:` (a whole session), `txstart:`/`txstop:`
  (the OCPP 2.0 split form, paired up by transaction id here), `mv:`,
  `sn:`, `rs:`, `rss:`, `se:`, `dto:` — all parsed per
  `ICUTransactionItem`, with the raw text kept so an unrecognised variant
  still comes out.
* **Logo upload** rides the same firmware channel, like the app: any common
  image format is converted (see below), NG chargers get a `.fwu` package
  (object stream + CRC'd wrapper + AES-128-CBC with the app's hardcoded key
  + the 160-byte `0xA1FE0013` header, with the device's fixed status icons
  and fonts embedded verbatim), AHP chargers get a `.tvf` package (the PNG
  inside a CRC'd-header + tar.gz container). The device applies it on its
  own; no reboot or commit is sent. Requires the `pillow` and `cryptography`
  dependencies (installed by default).

### Licensing (optional charger features)

From firmware 3.4.0 (NG) / 1.4.0 (AHP) on, chargers gate optional features
behind a vendor-issued license: RFID reader, ISO 15118, load balancing,
payment terminals, and the **personalized display** that logo upload needs.
The state lives in three properties that only answer to explicit `ids=`
reads (they appear in neither the category walk nor the EDS catalog):

| Property | Meaning |
| --- | --- |
| `21A0_0` | device-unique id the license key is derived from |
| `21A1_0` | installed license key (`XXXX.XXXX.XXXX.XXXX.XXXX.XXXX`) |
| `21A2_0` | installed feature bitmask (e.g. bit `0x1000` = personalized display) |

`alfenctl info` (or `license`, which defaults to `show`) shows the
installed features, the raw feature bits and the license key; `export` includes all three properties,
so a backup also documents the licensing state. **The charger enforces the
license at the upload stage itself** (confirmed from its own event log: a
syntactically valid logo package uploads with HTTP 200, then the charger
logs *"Unable to upload logo: Personalized display feature is locked!"* and
keeps the default logo). `logo` therefore refuses up front when the
feature is not licensed; `logo --force` uploads anyway (for testing), but
the logo will not be applied.

Install a new license key from your vendor with `license set`:

```console
$ alfenctl license set 0011.2233.4455.6677.8899.AABB --station garage
License key set to 0011.2233.4455.6677.8899.AABB.
The charging station will reboot on its own to install any new feature(s);
check with 'alfenctl license show' once it is back.
```

`set` validates and reformats the key the way the app's own dialog does
first — six hex groups, any separator (dots, dashes, spaces, ...), so a key
copied with the wrong punctuation or missing leading zeros still comes out
right — and refuses before sending anything if it does not parse. It is
still, underneath, the plain property write `set 21A1_0 <key>` always was;
the charger installs whatever the key covers and reboots on its own, same
as the app's dialog describes and neither it nor `alfenctl` waits for.

