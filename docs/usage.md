# Usage

One section per thing alfenctl does, with the commands to type. The
[README](../README.md) has the command table and the settings file;
[reference.md](reference.md) has the global options and exit codes.

Back up one charger's writable configuration and restore it later:

```console
$ alfenctl export charger-config.json --station garage --writable-only
$ alfenctl import charger-config.json --station garage --dry-run   # preview the diff
$ alfenctl import charger-config.json --station garage             # asks before writing
```

Upgrade firmware (checks first, asks, uploads, waits through the reboot,
commits, prints the new state):

```console
$ alfenctl firmware 'NG9xx 7.4.5-4415.fwi' --station garage
...
Upload complete; the charger is now installing and rebooting (usually ~2m50s, giving up after 15m00s).
  Rebooting  poll 3  status: no response (rebooting)  elapsed 47s / ~2m50s  next poll in 3s
```

The upload takes about a minute and a half (the charger reads it at
~19 KB/s); the install and reboot after it usually take **two to three
minutes** on an NG910. `--install-timeout` is the point at which we give up
and call the upgrade failed, not an estimate — it defaults to the 900 s the
Windows app uses (`ICULanDevice.StartUpload` fails past that with "it took
too long!"), while the same loop stops expecting the charger back after
170 s, which is the figure shown above.

### Picking a firmware from Alfen's server

Leave the file out and `alfenctl` asks Alfen's own firmware server what it
publishes for the charger in front of it, and offers you the choice:

```console
$ alfenctl firmware --station garage
Selected station: ACE0781464 (NG910-60027), firmware 5.8.1-4123

No firmware file given; asking ftp.alfen.com what is available...

Firmware for NG910-60027 on ftp.alfen.com/Firmware (now running 5.8.1-4123):

   #  File                                      Version       Released       Size  Notes
   1  NG9xx 7.4.5-4415.fwi                      7.4.5-4415    2026-08-05   1.8 MB  upgrade; ! install 6.6.2 first
   2  NG9xx 7.3.0-4411.fwi                      7.3.0-4411    2026-07-28   1.8 MB  upgrade; ! install 6.6.2 first
   3  NG9xx 7.1.6-4345.fwi                      7.1.6-4345    2025-09-17   1.8 MB  upgrade; ! install 6.6.2 first
   4  NG9xx 6.6.2-4396-BL-upgrade-B.fwi         6.6.2-4396    2026-04-09   1.0 MB  upgrade
   5  NG9xx 6.6.2-4396-BL-upgrade-A.fwi         6.6.2-4396    2026-04-09   1.0 MB  upgrade
   6  NG9xx 5.6.1-4414-B.fwi                    5.6.1-4414    2026-07-28   1.0 MB  downgrade
   7  NG9xx 5.6.1-4414-A.fwi                    5.6.1-4414    2026-07-28   1.0 MB  downgrade

Choose a firmware [1-7], default 4, or 'q' to cancel:
```

(That table is the real content of `ftp.alfen.com/Firmware` as of
2026-08-30, judged against this charger.)

The chosen release is downloaded to `~/.cache/alfen/firmware`
(`--cache-dir`, reused on later runs) and then goes through the same
compatibility check and confirmation as a file you name yourself. Should
Alfen publish a release as a `.zip` bundle (image + certificate + signature
+ OCPP key list — the shape of the bundles Alfen hands out directly), it is
unpacked and the image inside it is what gets uploaded; the server itself
currently carries bare images only.

* `alfenctl firmware --list` prints the table and stops — no upgrade.
* `-y/--yes` takes the default pick without asking, and refuses when
  there is no clear next release rather than guessing.
* Nothing is downloaded until you have chosen.
* The web UI's *Actions* tab shows the same list, with the next release
  marked. An image that is not a valid next step for this charger — wrong
  product code, or a stepping stone missing — is listed with its reason but
  cannot be started from the browser; installing one of those anyway stays a
  deliberate act in a terminal.

**Which releases are offered.** The app filters only on the file extension,
so it offers every `.tfw` to every AHP-family charger. `alfenctl` also
matches the release's product code against the charger's model — `NG9xx`
covers NG900/NG910/NG920 (`x` is Alfen's digit wildcard) and `AHP` covers
AHP02/AHPDC, while an `AHWP01` image is not offered for an `AHP02`. If that
leaves nothing at all — Alfen does retire a product code from the server
while the chargers are still in the field — the family's images come back
anyway, each flagged with what it was built for, so you never see less than
the app would show. `--all` lifts the model filter outright; the extension
filter always stays.

Each row is annotated with what installing it would mean for *this* charger:
upgrade, downgrade or currently installed, whether it crosses the 5.0
boundary (which needs `--new-password`), and whether Alfen's 6.6.2 stepping
stone is required first — the app showed that one as a standing red label
regardless of the release you picked. The default pick is the newest
release that is a valid *next* step, so a charger below 6.6 is offered
6.6.2 rather than a 7.x it should not jump to.

The server, credentials and folder can be overridden in `alfen.toml` if
Alfen ever moves or rotates them:

```toml
[firmware]
site = "ftp.alfen.com"
username = "installer"
password = "..."
directory = "Firmware"
```

Put your logo on the splash screen (any common image format; PNG for AHP):

```console
$ alfenctl logo company-logo.png --station garage
```

### Logo images

Any image size and any format Pillow can read (PNG, JPEG, BMP, GIF, …) works
on NG chargers — the conversion is the charger display's, not the file's:

1. **Transparency is flattened onto white** (an image with an alpha channel
   or a transparency mask is composited over a white background).
2. **The image is scaled to fit the display's logo box while preserving its
   aspect ratio** — it is never cropped and never stretched. The box is the
   display size read from the charger (properties `12896_3`/`12896_4`, e.g.
   320×165) minus a 16-pixel margin (8 per side, like the app's dialog).
   The larger of the two scale ratios wins, computed with integer floor:
   one axis ends up exactly filling the box, the other comes out equal or
   smaller. Large images are downscaled, small ones upscaled, the same way.
   A 1200×1200 image onto a 304×149 box becomes 148×148, shown centered.
3. **Colors are reduced to a palette of at most 128** without dithering
   (photographs keep looking fine; subtle gradients can band).

In other words: make the logo roughly display-shaped (wide) and it will use
the whole box; a square or tall logo will be letterboxed with white bars on
the left and right. There is no cropping, no way to fill the box from a
differently-shaped image, and no color-count knob — that is the vendor's
conversion, followed exactly.

AHP chargers (the new generation) are different: they take the **PNG as
is**, with no scaling or quantization, so prepare it at display size
yourself; other formats are rejected.

`logo --save FILE` writes the packaged image out instead of uploading it —
the app's *Create Image Update file*, for handing the package to a back
office to distribute. It still needs a charger to say which container to
build (`.fwu` for NG, `.tvf` for AHP) and how big the display is, but it
does not need the *Personalized display* licence: that gates what a charger
accepts, and the file may well be meant for another one.

### Chargers with no display

Not every station has a screen — an Eve Single S-line has LEDs and nothing
else — and one that has none accepts the upload and shows it nowhere. A
station is credited with a display when it publishes the display descriptor
`12896_1` and a logo box at `12896_3`/`12896_4` that is not zero, or when it
is one of the handful of models the vendor app knows has a fixed screen
without describing one (Eve Mini, NG910-60014, NG910-60034, and the
dual-plug NG920s). That is `ICULanDevice.HasDisplay`, and its own dialog
greys the upload button out and says so.

`alfenctl logo` refuses the same way, and so does the browser — the Actions
tab disables the control and the *Display and LEDs* card is marked *no
display*, with the brightness left where it is because `sysIntensity` drives
the LEDs too. `--force` sends the package regardless, which is the only way
to find out what a particular charger really does with one:

```console
$ alfenctl logo company-logo.png --force --station garage
warning: this charger reports no display; uploading anyway (--force)
```

The same flag covers a station whose *Personalized display* feature is not
licensed, which is a separate gate on the same upload.

### Event log

`alfenctl log` pulls the charger's own event log (the one the Windows app
shows in its *Log* panel) and writes it chronologically, oldest line first.
Only the part you ask for is downloaded:

```console
$ alfenctl log --station garage                    # since local midnight (default)
  Downloading log  [########################] 100%  2560 lines  back to 2026-08-31 19:54
Downloaded 2560 lines in 10 pages (2026-08-31 19:54:51 .. 2026-09-01 20:47:36) in 0.6s
note: dropped 421 fetched lines older than the cutoff (the charger pages the log in fixed-size blocks)
Wrote 2139 log lines to ACE0781464.log
```

`--since` takes `today`, `yesterday`, a relative span (`45m`, `12h`, `7d`,
`3w`), an absolute date or datetime (`2026-08-25`, `2026-08-25T06:30`,
`25.08.2026`), or `all`; `--all` is the shorthand for the last one. Without
a cutoff the whole buffer comes down, which on a busy charger is tens of
thousands of lines and a few minutes of requests — hence the default of
"today".

The charger holds its log in a fixed-size flash ring buffer and has no API
for how far back that reaches, so `--range` finds out by bisecting the page
offset — about fifteen requests instead of one per page:

```console
$ alfenctl log --range --station garage
Log buffer on ACE0781464:
  oldest entry : 2026-08-24 18:22:00  (8.1 days ago)
  newest entry : 2026-09-01 20:48:05  (just now)
  lines        : 20000 (in pages of 256)
  found in     : 15 requests

Export all of it with: alfenctl log --since 2026-08-24
```

An export that runs off the end of the buffer says so too, so asking for
more than the charger kept is never silent.

`--follow` turns the export into a live tail — the charger has no
streaming endpoint, so this re-reads the newest page every couple of seconds
and prints what is new, saying so plainly if the charger logged faster than
we read. `--type` filters on the kind the firmware tags each line with
(`info`, `warning`, `error`, `com`, `user`, `reset`, `console`, `security`),
which is what the app's log view does with its row of toggle buttons:

```console
$ alfenctl log --follow --type error --station garage
Following ACE0781464's log; press Ctrl+C to stop.
4295_2026-08-29T12:41:54.001Z:ERROR:fw_update.c:388:Rejecting upload: feature not licensed
```

### Charging sessions

`alfenctl transactions` reads the charger's transaction database — what it
charged, for whom, and what it still owes its backoffice — and writes the
charging sessions as CSV:

```console
$ alfenctl transactions --station garage
Read 1284 records in 43 pages
119 charging session(s).
Wrote ACE0781464-transactions.csv
```

| Column | |
| --- | --- |
| `transaction_id`, `socket` | which session, on which outlet |
| `start_time`, `stop_time`, `duration` | charger local time |
| `start_kwh`, `stop_kwh`, `energy_kwh` | meter readings and the difference |
| `average_kw` | energy over duration |
| `start_tag`, `stop_tag` | the RFID tags that started and stopped it |
| `stop_reason` | `ev-disconnected`, `remote`, `power-loss`, … |
| `complete` | `no` if the session was still running, or its stop record has rolled out of the buffer |

The database holds more than sessions: periodic meter values, status
notifications, reservations, security events (firmware updates, tamper
detection, clock changes) and clock-offset corrections. `--json` emits
every parsed record instead of just the sessions, and `--raw` gives the
charger's own record text, which is what the Windows app puts in its CSV.
`--since` accepts the same forms as `log --since`, and `--erase` clears the
database (after confirming — it drops records not yet sent to the
backoffice).

`--summary` answers the question the CSV usually gets opened for, without
opening it:

```console
$ alfenctl transactions --summary --station garage
MONTH    SESSIONS  KWH      TIME      KWH/SESSION
2026-06  31        412.500  84h 12m   13.306
2026-07  38        501.250  102h 40m  13.191
total    69        913.750  186h 52m  13.242
```

`--summary socket` and `--summary tag` group the same totals the other two
ways, and `--socket N` narrows any of them. A session with no end record —
still running, or its stop record has rolled out of the buffer — has no
energy to count, so it is counted separately and said out loud rather than
quietly shrinking the month.

### Live status

`alfenctl status` is the app's *Monitoring* panel in the terminal — the
properties are all reachable with `get`; what this adds is knowing which
ones matter and what their numbers mean:

```console
$ alfenctl status --station garage
ACE0781464 (NG910-60027), firmware 7.4.5-4415

  Socket 1     available
               Mode 3: A (no vehicle)
               LED: available
               Power: main off, bypass off
               Display: Charging Suspended by EV

  Limits       16 A station, 16 A installation, 16 A safe

  Voltage      231.0 / 231.0 / 230.7 V
  Current      0.0 / 0.0 / 0.0 A
  Power        0.00 kW
  Delivered    1247.310 kWh

  Temperature  42.6 C  (alarm below -25 or above 60)
```

`Delivered` is the meter's own lifetime total (`2221_22`) — what a session
is measured against. It is not in any property category, so it is asked for
by id along with the walk; a charger that does not answer for it simply has
no such line. The register counts watt-hours, whatever the vendor's EDS says
about it, so what you see here is a thousandth of what `alfenctl get 2221_22`
prints.

A `Consumed` line (`2221_26`) joins it on a station that can send energy back
the other way, into the grid. One that cannot reports zero there for ever, so
the line stays out until the number means something.

One correction worth knowing about if you have scripted against an older
version: `Power` used to be read from `2221_11`, which the bundled EDS
labels "ActivePower" and which is really Cos φ Total. The vendor app reads
the total from sub 22 (`2221_16`), and a live NG910 agrees — its `2221_12`
reads 50.11, a mains frequency at the app's index for it. That is where the
power comes from now.

The `Display:` line is what the charger's own screen is saying
(`0x3190_1`), and when that is an error state the code behind it
(`0x3190_2`) is printed the way the app writes it — `401: Inside
temperature high`, with the app's own severity. A socket taken out of
service is marked as such, and so is a whole station that has been.

Sections the charger does not publish are left out rather than guessed at,
and `--json` gives the same snapshot for scripting. `--watch` re-reads and
redraws in place until Ctrl+C (every 2 s, or `--watch 5` for another
interval) — the app's panels refresh on their own; here you ask for it.

### Current limits and brightness

Two settings get changed far more often than the rest, so they have their
own commands rather than a property id to remember. `current` is the app's
*Power* panel: the maximum for the whole station and the maximum for each
socket.

```console
$ alfenctl current --station garage
Charging current limits:

  Station maximum       32 A
  Socket 1 maximum      16 A
  Socket 2 maximum      16 A

Set a socket's limit with: alfenctl current set 10

$ alfenctl current set 10 --station garage
Socket 1, Socket 2 set to 10 A.

$ alfenctl current set 8 --socket 2 --station garage
Socket 2 set to 8 A.

$ alfenctl current set 25 --station-max --station garage
The station maximum set to 25 A.
```

Only the sockets the station has are listed. It answers for the other one
regardless — a single-socket NG910 builds socket 2's `mainNormalMaxCurrent`
whether or not there is a socket 2 — so `sysNrOfSockets` is what decides,
not the reply.

The charger takes any of these; what it does not do is tell you when they
contradict each other, so alfenctl says it. A socket limit above the
station's does nothing (the lower one wins); sockets that add up to more
than the station maximum only work with static load balancing or a Smart
Charging Network — the Windows app quietly rewrites both sockets to half the
station current when it finds that, which is worth knowing before it
happens; and a limit under 6 A does not charge slowly, it does not charge,
because Mode 3 cannot offer a car less than that. All three are warnings and
none of them is a refusal: the floor for a *write* stays the 1 A the vendor's
own dialog allows, since commissioning a charger is not charging a car.

`brightness` is the app's *Intensity* setting: how bright the LEDs and the
display are, and whether the charger dims itself when nothing is happening.

```console
$ alfenctl brightness --station garage
Display and LED brightness:

  Intensity  100%
  Auto dim   on

$ alfenctl brightness set 40 --auto off --station garage
Display and LED brightness:

  Intensity  40%
  Auto dim   off
```

On newer firmware the auto-dim setting is a bit field with separate reasons
to dim (by time, by inactivity, for QR codes); `--auto` moves only the bit
that turns dimming on and off, and leaves the rest as it found them.

`current show` also reports the live half of the picture, when the station
carries it: what an external controller is asking for right now
(`0x212A_0`), and what static balancing, active balancing and the P1 meter
are each allowing. That is how a limit that was *configured* is told apart
from the limit actually in force:

```console
$ alfenctl current --station garage
Charging current limits:

  Station maximum     32 A
  Socket 1 maximum    16 A
    external request  10 A
    now allowing      16 A static, 12 A active
```

`current set 6 --external` writes that request rather than the stored
maximum. It is a RAM register: a solar or tariff controller drives it, and
the station returns to its configured limit on the next boot.

### Taking a socket out of service

```console
$ alfenctl socket --station garage
Sockets:

  Station   in service
  Socket 1  in service
  Socket 2  out of service

$ alfenctl socket enable 2 --station garage
Socket 2 is back in service.
```

All of it lives in one bit field (`0x205F_0`), holding every socket's bit
and the station's own, so each change is a read-modify-write: disabling
socket 2 leaves socket 1 exactly where it was. Disabling stops a session
that is charging on that socket, so it asks first, or takes `-y`.

(The Home Assistant integration models this register as a plain
Operative/In-operative select writing 0 or 2, which is right for a
single-socket station and takes both sockets out on a double one.)

### Load balancing and solar charging

`alfenctl loadbalancing` (alias `lb`) is the app's *Load balancing* panel:
the mode, the meter it reads, the currents it works to, and the solar
settings underneath them.

```console
$ alfenctl lb --station garage
Load balancing:

  Mode               active
  Meter protocol     DSMR/SMR P1
  Max meter current  25 A
  Safe current       6 A
  Solar charging     comfort
  Green share        50%

$ alfenctl lb set --safe-current 10 --solar-mode green --station garage
```

The mode is a bit field, not a choice: bit 0 is static balancing and bit 1
active, so turning one on leaves the other as it was. Where a setting is
on but the station is not licensed for it, `show` says so — the charger
accepts the write either way and simply does not act on it.

### Who may start a session

`alfenctl auth` is the companion to `alfenctl tags`, which manages the list
but could never turn it on:

```console
$ alfenctl auth --station garage
Authorization:

  Mode             RFID
  Local whitelist  on
  OCPP local list  off
  Offline          accept known tags

$ alfenctl auth set --mode rfid --whitelist on --station garage
```

The offline action is one setting stored as two registers (`0x2127_0` and
`0x213E_0`, read as a two-bit number); `--offline refuse|known|any` writes
both halves in one batch and never sends the one combination the vendor's
enumeration does not define. Changing the mode takes effect after a reboot,
and the command says so.

### The backoffice connection

`alfenctl ocpp` answers "why is this charger not talking to its CSMS"
without a dozen `get` calls across registers the EDS does not even name:
the connect method, the protocol version, the wired and mobile URLs, the
heartbeat, the timeouts and the proxy.

```console
$ alfenctl ocpp --station garage
$ alfenctl ocpp set --heartbeat 300 --station garage
```

The heartbeat goes to `0x2085_0`, which is writable; `0x2086_0` beside it is
the interval the backoffice negotiated and is read-only. The authorization
key and the proxy password are not properties at all — `alfenctl secret set`
installs those.

### Charging now despite a profile

An installed charging profile is enforced by the charger whether or not
anyone is watching, which is the point of the UK regulation. `direct-start`
is the per-socket escape hatch from it:

```console
$ alfenctl direct-start --station garage
SETTING       VALUE
Socket 1      follow profile
Random delay  600 s

$ alfenctl direct-start on --socket 1 --station garage
```

With no profile installed there is nothing for it to override, and the
command says so rather than writing blindly. `--random-delay` carries the
randomised start delay beside it; below 600 s the station is no longer
UK-compliant, which `show` points out without refusing the write.

### Checking a charger over

`alfenctl doctor` asks in one read-only pass what the vendor app validates
one panel at a time:

```console
$ alfenctl doctor --station garage
ACE0781464 (NG910-60027), firmware 7.4.5-4415

!! sockets: the whole station is out of service; no socket will charge
      alfenctl socket enable
 ! limits: socket 1 is set to 16 A, above the station maximum of 10 A
 ! clock: the charger's clock is 4 minutes behind, so its transaction
   timestamps will be too
      alfenctl time sync

Could not check:
  tilt: this charger does not report a tilt sensor
```

Each finding names the command that would deal with it. A check that could
not run is listed as such rather than counting as a pass, and the exit code
is non-zero only for something that stops the station charging — so it is
usable from cron.

### Settings files and presets

`export` writes alfenctl's own JSON by default and the Windows app's
`<Settings>` XML when the output file ends in `.xml` (or with `--xml`);
`import` reads either, recognised from the content rather than the name. So
a backup taken here can be loaded by the ACE Service Installer, and the
other way round.

Alfen publishes ready-made property sets — meter wirings and backoffice
configurations — beside the firmware on its own server:

```console
$ alfenctl preset
Presets on ftp.alfen.com:

  ABB B23 TCP        Modbus TCP meter map     2026-07-31
  Eastron SDM630     Modbus RTU meter map     2025-03-01

  ...and 467 backoffice presets.
  Search them with: alfenctl preset <part of the name>

Apply one with: alfenctl preset <name>

$ alfenctl preset "ABB B23" --dry-run --station garage
```

A meter preset goes through the same diff-preview-confirm path as `import`,
including the device-bound property guard.

A **backoffice** preset is a different thing wearing the same word. Alfen
publishes ~930 of them, and every one is a signed `.fwi` blob rather than a
settings document — there is nothing to preview inside one. Installing it
is the sequence the Windows app uses: clear the current backoffice
properties, push the blob through the firmware channel, write the preset's
name into `0x2076_0`, reboot. It therefore asks first, and takes `-y`:

```console
$ alfenctl preset Abel&Co --station garage
Preset Abel&Co (backoffice preset), 1152 bytes.
This clears the current backoffice settings, uploads the preset through the
firmware channel, and needs a reboot to take effect.
Install Abel&Co? [y/N]
```

Each one is published once per encryption key, as a trailing `-A`/`-B` on
the file name; the charger's own firmware version picks the copy it can
decrypt. `--save FILE` writes the blob out instead of installing it.

**Encrypted settings files (`.exml`) are supported**, both ways: `export
FILE.exml` (or `--exml`) writes one, and `import`/`preset` decrypt one
automatically — recognised from its content, not its extension, same as
plain `.xml`. The app encrypts what it saves under this extension:
AES-256-CBC/PKCS7 under a key derived from the fixed passphrase `"Alfen"`
by .NET's `PasswordDeriveBytes` (`ICUSettings.EncryptDecrypt`, called from
`PropertyStorage` with that literal string), a fixed salt and IV, then
base64. `PasswordDeriveBytes` is not PBKDF2 — its non-standard key
stretching is reimplemented in `alfenctl.settings._password_derive_bytes`
— and is checked byte-for-byte in the test suite against the one real
encrypted sample available, the app's own `InstallerConfigV3.dat` (same
scheme, a different hardcoded passphrase, `ICUConfig.cs`).

### Passwords

Firmware 5.0 and later (and every AHP) requires a unique per-charger
password instead of the shared default:

```console
$ alfenctl password set --station garage            # prompts, so it stays out of shell history
$ alfenctl password temporary --hours 8             # reverts by itself afterwards
$ alfenctl password recover AB12-CD34 --host 192.168.11.42
```

`recover` is the way back in when the password is lost: it takes the reset
code printed on the charger and puts it back on its factory default, and is
**the one command that runs without logging in**. The charger rate-limits
wrong codes, and the refusal is reported as such — wrong code, locked out
for N minutes, or recovery not supported on this station.

`password pin` is a separate, independent credential: the 4-6 digit PIN
that gates the **Eve Connect mobile app**'s access to the charger, not the
admin login above.

```console
$ alfenctl password pin 4821 --station garage        # set the app access PIN
$ alfenctl password pin --allow-empty --station garage  # enable without one
$ alfenctl password pin --disable --station garage   # disable app access entirely
```

### The charger's clock

A charger boots with its clock at the firmware build date and only jumps
forward once something sets it — so an unsynced station stamps its event log
and its transaction records with a time that can be years out, and firmware
signature validation (which checks certificate validity against that clock)
starts refusing perfectly good images. `alfenctl time` shows where it stands
and `time sync` fixes it, as the app's *Sync time* button does:

```console
$ alfenctl time --station garage
Charger clock:

  Charger (UTC)  2024-03-01 09:15:00
  This computer  2026-09-04 21:08:28
  Difference     2.5 years behind this computer
  Time zone      UTC+01:00, daylight saving on
  Charger local  2024-03-01 10:15:00

Set it from this computer with: alfenctl time sync

$ alfenctl time sync --station garage
ACE0781464's clock set to 2026-09-04 21:08:28 UTC (it was 2.5 years behind this computer).
```

Setting it is two writes, both of which the app makes (`ICULanDevice
.SetDate`): `sysDateTime` (`0x2059`, milliseconds since the Unix epoch) and
then the firmware's own `date` console command — `POST /api/datetime` on
AHP. The upload paths do the same thing before sending an image, which is
why a stale clock has never blocked `firmware` or `logo` here.

### Write-only secrets

Some of what a charger needs can never be read back, and cannot be written
through the property API either: the EDS marks those properties `wo` with
`DataType="0x000F"` (DOMAIN) and `POST /api/prop` will not take them. The
OCPP **back-office authorization key** is the one that matters in practice —
without it you can point a charger at a backoffice with `set` but not
authenticate to it. The app installs these through a separate endpoint
(`ICUDomain.AddOrUpdateItem`: `POST /api/domain` with the value hex-encoded),
and so does `alfenctl secret`:

```console
$ alfenctl secret
Secrets that can be installed (write-only: the charger never reads them back):

NAME               TAKES  WHAT IT IS
auth-key           VALUE  OCPP back-office authorization key (security profiles 1 and 2)
proxy-password     VALUE  password for the HTTP proxy the charger connects out through
ca-cert            FILE   root CA that signs the back office's TLS certificate (PEM) *
client-cert        FILE   the charger's own certificate chain and key, for OCPP security profile 3 (PEM) *
manufacturer-cert  FILE   manufacturer root CA (PEM) *

$ alfenctl secret set auth-key --station garage      # prompts, so it stays out of shell history
$ alfenctl secret set ca-cert backoffice-root.pem --station garage
```

`alfenctl secret` on its own needs no charger. The two value-typed secrets
are the ones the app's own UI writes; the certificate types are named by its
`EDomainItemType` table but never sent by it, so they are marked untested
above rather than presented as verified. The firmware validation and
encryption keys, the private CSR and the password reset code are in that
same table and deliberately **not** exposed: a wrong value there either
breaks firmware updates or weakens the charger's access control, and there
is no way to check a guess.

### Tilt sensor

A pedestal charger reports being knocked over by comparing its accelerometer
against three stored setpoints, and calibration means storing the current
reading as "upright" (`PanelAlerts.OnCalibrateClicked` copies `0x2207`–
`0x2209` into `0x2210`–`0x2212`). So it is only meaningful once the station
is installed and standing as it will stand, which is what `alfenctl
calibrate tilt` says before it writes:

```console
$ alfenctl calibrate tilt --station garage
Tilt sensor:

  X   reading     10   upright 0
  Y   reading     -4   upright 0
  Z   reading    990   upright 0

Calibrating stores the reading above as 'upright', so the charger
must already stand in its final, level position.
Store this position as upright? [y/N]
```

### RFID tags

`alfenctl tags` reads and edits the charger's own authorization whitelist —
the list it consults when it cannot ask a backoffice:

```console
$ alfenctl tags --station garage           # `tags` on its own means `tags list`
TAG           STATUS   EXPIRES
04A1B2C3D4E5  active   <no expiry date>
04FFEE112233  blocked  2027-06-30

2 tag(s).
```

`add` writes a whole record (`--parent`, `--status active|blocked|deleted|master`,
`--expires YYYY-MM-DD`); `remove` and `clear` take tags away; `learn` puts
the charger into the app's *add tag* mode, where it enrols whatever card is
next presented at its reader.

`import` applies a file — JSON from `tags list --json`, the CSV from
`tags list --csv`, or just a list of tag ids one per line, which is what a
spreadsheet of cards exports to. It previews the changes first, writes only
what differs, and leaves tags the file does not mention alone unless you
pass `--replace`:

```console
$ alfenctl tags import site-cards.csv --replace --station garage
  add    04NEW00112233  active   <no expiry date>
  update 04A1B2C3D4E5   blocked  2027-06-30
  remove 04FFEE112233

Apply 3 change(s)? [y/N]
```

`master` shows or sets the **master tag** — one RFID tag that always
authorises, independent of the whitelist above:

```console
$ alfenctl tags master --station garage
Master tag: 04A1B2C3D4E5 (enabled)

$ alfenctl tags master 04NEW00112233 --station garage   # set and enable
$ alfenctl tags master --clear --station garage         # clear the tag id
$ alfenctl tags master --disable --station garage        # keep the tag, turn the mode off
```

### The network

`alfenctl network` says where the charger is: its Ethernet address and how
it got one, the Wi-Fi station and access point, and the modem block. It is
read-only on purpose — writing an interface's own address is how a station
is lost, so that stays an explicit `alfenctl set 207D_2 …`.

`alfenctl wifi` asks the charger's own radio what it can see, and then joins
one, rather than leaving the SSID and passphrase to be typed blind:

```console
$ alfenctl wifi --station garage
SSID       SIGNAL       SECURITY
home-net    -45 dBm excellent  WPA2-PSK (AES)
guest-net   -70 dBm fair       unknown (0x0) (unsupported)

2 network(s). Join one with:
  alfenctl wifi connect 'home-net' --psk <passphrase>

$ alfenctl wifi connect home-net --station garage
Passphrase:
Sent the settings for 'home-net'.
```

The SSID, passphrase and security type go in one batch, so the radio is not
asked to connect halfway through. `--psk` rather than `--password`, because
the connection options already have a `--password` for the charger's own
login and `wifiPSK` is the vendor's own name for this one. `wifi ap` turns
the charger's own access point on or off, and `wifi disconnect` switches the
radio off while keeping the settings.

**A scan needs the radio switched on.** The scan is the charger's own radio
listening, so with `sysWifiEnabled` (`0x3284_0`) clear there is nothing to
listen with: `/api/wifiscan` answers an empty list, quickly, and it reads
like an empty band. The vendor's own installer has the same behaviour and
simply greys its *Scan Wi-Fi networks* button out while the flag is clear.
`alfenctl network` shows both halves — the flag and the radio's own
`wifiStatus` — and a scan that comes back empty says which one is in the
way:

```console
$ alfenctl network --station garage
Network
  Ethernet MAC       AA:BB:CC:DD:EE:FF
  Ethernet address   192.168.11.42 (DHCP)
  Wi-Fi              disabled
    radio            disabled

$ alfenctl wifi scan --station garage
No Wi-Fi networks found.
note: the Wi-Fi radio is switched off (sysWifiEnabled, 0x3284_0).
A scan is the charger's own radio listening, so it finds nothing while the
radio is off.
Switch it on and scan again with:
  alfenctl wifi scan --enable
```

`alfenctl wifi enable` writes that one flag and waits for the radio to
report itself running; `wifi scan --enable` does both and then scans. The
flag takes effect without a reboot — the charger's own access point is the
part that needs one — but the radio still takes a few seconds to come up,
which is what the wait is for. Nothing is written without `--enable`: a
station reached over Ethernet often has its Wi-Fi off deliberately.

**A radio that is on can still hear nothing yet.** `/api/wifiscan` comes
back in about three seconds where the vendor's client allows eleven, which
is the shape of an endpoint handing back the survey the radio already
finished rather than running a fresh one to order. A radio that has just
been switched on has no survey yet, so `wifi scan` asks three times before
it believes an empty list (`--attempts N` to change that, `--attempts 1`
for the single shot the vendor takes). When the list is still empty and the
radio is running, the scan says what is left to check — the band, the
distance, and trying again in a minute — rather than reporting an empty
band as fact.

An answer the parser did not understand is reported as exactly that, not as
"no networks found"; `--debug` then prints what the charger actually sent.
Networks broadcasting no SSID are counted rather than dropped silently:
they were heard, they just cannot be joined by name.

Addresses read back as `192.168.000.092` are marked `(unset)`. That string
is the factory default every `commIPaddress` register carries until an
interface acquires one, so seeing it under both Wi-Fi and the modem means
neither is connected, not that they share an address.

### Smart-meter test

`alfenctl meter-test` shows live per-phase current and power from an
external Modbus TCP/RTU smart meter — the app's commissioning check that a
meter is wired correctly (and its CTs are the right way round) before it is
trusted for load balancing:

```console
$ alfenctl meter-test --station garage
  Current L1       16.02 A
  Current L2       15.98 A
  Current L3       0.0 A
  Active power L1  3.68 kW
  Active power L2  3.65 kW
  Active power L3  0.0 kW
```

### Custom meter register map

A meter the charger does not know by name is described to it register by
register: which Modbus register carries each measurand, how to read it, and
what to scale it by. That map lives in four parallel array properties
(`0x2570`–`0x2573`), and `alfenctl meter-map` reads and writes it the way the
app's *Custom register mapping* dialog does:

```console
$ alfenctl meter-map --station garage
Custom Modbus register map (2 of 12 slots used):

MEASURAND      REGISTER  READ AS     SCALE
CURRENT_L1     0x0006    UNSIGNED32  x 0.001
POWER_REAL_L1  0x0010    FLOAT32     x 1

$ alfenctl meter-map apply socomec-e23.json --station garage
```

Writing is bracketed the way the firmware expects (`ICUModbusRegmap
.WriteToDevice`): Modbus balancing into socket mode, load balancing off, the
four arrays, load balancing back on. One deviation — the app always turns
both static *and* active load balancing on afterwards, while alfenctl puts
back whatever the charger had, so applying a map cannot quietly enable
balancing that was off. If a write fails part-way, the previous mode is
restored anyway rather than leaving the charger with balancing switched off.

The map files are Alfen's own JSON, published in the same `TCPPresets/` and
`RTUPresets/` folders as the settings presets — so `alfenctl preset` lists
them alongside, and applying one goes through this same path:

```console
$ alfenctl preset --station garage
Presets on ftp.alfen.com:

  ABB B23 TCP    Modbus TCP meter settings  2025-07-31
  Socomec E23    Modbus TCP meter map       2025-07-31
```

`meter-map save FILE` writes the charger's current map back out in that
format. Only the smart-meter block is implemented: a second block at
`0x2560` exists for a central meter, but the app's two entry points both
open the dialog for a smart meter, and its own read and write paths disagree
about which meter type selects the other block — so that path has most
likely never run, and is not reproduced here on a guess.

### OCPP charging profiles

`alfenctl charging-profiles` manages the OCPP schedule objects the charger
enforces locally, independent of any backoffice:

```console
$ alfenctl charging-profiles --station garage   # the default action is `list`
No charging profiles installed.

$ alfenctl charging-profiles install-uk --station garage
UK Smart Charging default profile installed: charging is blocked
08:00-11:00 and 16:00-22:00 on weekdays, allowed the rest of the time.

$ alfenctl charging-profiles list --station garage
  -19061964 (UK Smart Charging default)

$ alfenctl charging-profiles show -19061964 --station garage
Profile -19061964  connector 0  Recurring  ChargingStationExternalConstraints  stack 1  unit A
  starts 2026-08-31T00:00:00Z
  +0d 00:00  limit 32 A
  +0d 08:00  limit 0 A
  +0d 11:00  limit 32 A
  ...

$ alfenctl charging-profiles clear -19061964 --station garage
```

`install-uk` is the one profile the app's own UI ever installs through this
endpoint — the default weekly schedule required by the UK's Electric
Vehicles (Smart Charging) Regulations 2021. `list`/`show`/`clear` work on
any profile a backoffice or `install-uk` has put there.

### Smart Charging Network

`alfenctl scn` creates, joins, and leaves an SCN — a group of chargers that
share one grid connection's current budget and take turns charging when
demand exceeds it:

```console
$ alfenctl scn create garage --station ace0781464
Checking the LAN for a name clash...
Created 'garage'; rebooting ACE0781464 to apply it.
  Rebooting  poll 3  status: no response (rebooting)  elapsed 12s / ~2m0s

$ alfenctl scn join garage --station ace0781465
Probing the LAN for the network's other members...
Updated 1/1 other member(s) with the new total.
Joined 'garage' as ACE0781465 (socket 1); rebooting to apply it.
  ...

$ alfenctl scn --peers --station ace0781464     # the default action is `status`
ACE0781464 is a member of Smart Charging Network 'garage':
  Socket id       0
  Total sockets   2
  Current limits  32 A total, 6 A socket safe, 32 A total safe
  Alternating     every 900 s

Probing the LAN for other members...

2 member(s) found:
  ACE0781464     socket 0  (this station)
  ACE0781465     socket 1

$ alfenctl scn leave --station ace0781465
Remove ACE0781465 from Smart Charging Network 'garage'? [y/N] y
Probing the LAN for the network's other members...
ACE0781465 removed from 'garage'.
Updated 1/1 other member(s) with the new total.
```

`create` starts a brand-new, single-member network with the app's own
defaults (32 A total, 6 A per-socket safe, 900 s alternating period —
override with `--total-current`/`--socket-safe-current`/
`--total-safe-current`/`--alternating-period`) and refuses if the name is
already in use anywhere on the LAN. `join` finds an existing network's
members, copies their shared settings, and picks the next free socket id
past the highest one in use (see **How it works** above for how that
differs from the app's own gap-filling). Both reboot the charger being
added, matching the app; `leave` does not, matching it too. `status
--peers` and both mutating actions **log into every charger mDNS finds on
the LAN**, using the target's own credentials, to see who else is in the
network — a station that does not answer, or rejects them, is skipped with
a warning rather than failing the command, since it is as likely to be
unrelated hardware on the same LAN as it is an actual member that happens
to be unreachable right now. A member that stays unreachable through a
`join`/`leave` keeps its old total-socket-count and settings until it is
reachable again or resynced by hand (`alfenctl get`/`set` on `2180_3` and
friends) — there is no way to tell those two cases apart without a login.

