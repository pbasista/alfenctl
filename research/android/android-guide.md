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

The output is a single ~38 MB JavaScript file. It is verbose and
repetitive, but it is *complete*: nothing in the app is hidden from it. All
findings cite `decompiled.js@<byte offset>` because most of the interesting
regions are single multi-megabyte lines.

## Step 3 — Mine the string table

hermes-dec's parser exposes the bundle's string table directly, which is the
fastest way to find things:

```python
from hermes_dec.parsers.hbc_file_parser import HBCReader

r = HBCReader()
r.read_whole_file(open("base/assets/index.android.bundle", "rb").read())
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
   maps the app renders, and `ChargingStationCommand.*` holds the labels of
   the console commands it offers (but not the command strings behind
   them — those come from the Windows app or a charger log).

Also worth mining: `CSLanguageValue` (~30,378,000) for the display-language
locale list, and the fetch batches (e.g. `'ChargingStation'` around
~28,656,000) for how the app groups ids into requests.

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
