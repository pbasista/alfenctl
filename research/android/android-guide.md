# Reverse-engineering the My Eve Android app

**My Eve** (package `com.alfen.myeve`) is Alfen's consumer Android app for
the Eve charger line. It is a React Native application whose business logic
— the complete property dictionary, validation rules, and display-name
translations — ships inside a Hermes bytecode bundle. The v2.3.1 XAPK from
APKPure was used; the same steps apply to any version.

The goal of the reproduction is the same evidence-per-id table as for the
Windows installer: the app's display name for every property, the value
bounds its forms enforce, and the enumerations it decodes. The result is
[`android-findings.md`](android-findings.md).

## Step 1 — Unpack the XAPK

An XAPK is a zip of APKs plus a manifest:

```console
$ unzip 'MyEve+-+Alfen_2.3.1_APKPure.xapk' -d xapk
$ unzip 'xapk/com.alfen.myeve.apk' -d base
$ ls base/assets/index.android.bundle          # the Hermes bundle (bytecode v96)
```

## Step 2 — Decompile the Hermes bundle

Use [hermes-dec](https://github.com/P1sec/hermes_dec) (0.1.7 was used):

```console
$ uv tool install hermes-dec
$ hbc-decompiler base/assets/index.android.bundle > decompiled.js
```

The output is a single ~38 MB JavaScript file that provides a navigation
aid rather than a complete source reconstruction. Decompiled function
bodies may be incomplete or inaccurate; native APK code is separate.
Most property findings cite `decompiled.js@<byte offset>` because many
regions occupy multi-megabyte lines. Verify call chains against the
original bytecode and record the bundle hash for reproducibility.

## Step 3 — Mine the string table

hermes-dec's parser exposes the bundle's string table directly, which is the
fastest way to find things:

```python
import io
from hermes_dec.parsers.hbc_file_parser import HBCReader

r = HBCReader()
r.read_whole_file(io.BytesIO(open("base/assets/index.android.bundle", "rb").read()))
for i, s in enumerate(r.strings):
    print(i, repr(s))
```

Then locate each string of interest in `decompiled.js` by byte offset
(e.g. `decompiled.js.find("eepromx erase config")`) and read the
surrounding module.

## Step 4 — Extract the three knowledge regions

1. **The id → name dictionary** (745 entries, English): a JS object literal
   mapping `'2056_00': 'Number of bootups'`-style keys to display names,
   around byte offset ~37,665,700. **Key format:** the app zero-pads subIds
   to 2 *hex* digits (`2051_00`, `20F0_0A`). Normalize when comparing.
2. **The validation rules** (211 writable properties): a module around
   ~36,072,000 with per-id `default/min/max/type/formRule/regex` objects —
   e.g. latitude `205C_01` bounded to −90..90. These are the bounds the
   app's commissioning forms enforce before it sends anything.
3. **The i18n descriptor families**: around ~17,870,000 for English. Keyed
   families like `MainStateDescriptors`, `LedStateDescriptors`,
   `Mode3StateDescriptors`, `DeviceStateDescriptors` hold the value → label
   maps the app renders.

The compiled `CSCommands` table defines console command strings separately
from the i18n labels. In the bundle identified below, #29352 (`0x67594a`)
maps the flash actions to `flash-info` and `flash-dump`. #29357 passes the
selected string to `station.api.executeCommand`; a separate
`{command, csName}` object supplies notification data. #20699, #22704–#22706,
and #20578 implement the default `POST https://<station>/api/cmd` route with
`{"command":"<literal>"}`. MyEve filters advanced choices by the station's
SSA login role. Firmware support and server-side authorization are separate
from this client-side filter.

Also worth mining: `CSLanguageValue` (~30,378,000) for the display-language
locale list, and the fetch batches (e.g. `'ChargingStation'` around
~28,656,000) for how the app groups ids into requests.

### Reproduce the console trace from the shipped XAPK

Run this Python in an environment containing `hermes-dec`, from the
`alfenctl` repository root. It reads archives in memory; it neither contacts
a charger nor executes any console command.

```python
import hashlib
import io
import zipfile
from hermes_dec.parsers.hbc_file_parser import HBCReader
from hermes_dec.parsers.hbc_bytecode_parser import parse_hbc_bytecode

with zipfile.ZipFile("research/android/MyEve+-+Alfen_2.3.1_APKPure.xapk") as outer:
    apk_bytes = outer.read("com.alfen.myeve.apk")
with zipfile.ZipFile(io.BytesIO(apk_bytes)) as apk:
    bundle = apk.read("assets/index.android.bundle")
assert hashlib.sha256(bundle).hexdigest() == (
    "343005158d1b85792de89d9e812f64630f6790cbd4da47d1a12718f4a206a1fb"
)
reader = HBCReader()
reader.read_whole_file(io.BytesIO(bundle))
for fid in (29352, 29357, 29359, 29360, 29363, 20566, 20790, 20699,
            22704, 22705, 22706, 20578, 20605, 22686, 11518, 22716):
    header = reader.function_headers[fid]
    print(f"\nFunction #{fid} @ {header.offset:#x}")
    for instruction in parse_hbc_bytecode(header, reader):
        print(repr(instruction))
```

The findings' console section describes the register and offset
interpretation. The reader retains the `BytesIO` stream and seeks it during
disassembly. Function IDs and offsets apply to the recorded bundle hash;
other releases require their own function maps.

## Step 5 — Corroborate

Compare against a live charger's `GET /api/prop` output: which of the 745
ids the device actually answers for, and whether the app's names and bounds
survive contact with the hardware (305 of the 311 properties a 7.4.5 NG910
reports are in the dictionary; the misses are listed in the findings).
Where the app and the Windows installer disagree, the installer wins — it
is the tool this project reimplements.

Everything extracted this way is in
[`android-findings.md`](android-findings.md): the property table with
per-row byte-offset evidence, the 211 validation rules, the descriptor
families and hardcoded enum tables, and the read/write hints.
