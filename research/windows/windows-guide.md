# Reverse-engineering the ACE Service Installer (Windows)

The **ACE Service Installer v4.3.0** is Alfen's Windows commissioning tool.
It is a .NET Framework WPF application that speaks the same HTTP API as the
charger's web interface. Everything below was reproduced with the v4.3.0_424
MSI; other versions should differ only in detail.

The goal of the reproduction is a per-property evidence table: for every
property id, its vendor name, the code or data file that proves it, and how
much to trust it. The result is
[`windows-findings.md`](windows-findings.md).

## Step 1 — Get the installer

Download the installer from Alfen's service portal (the same page that hosts
firmware releases), or use any copy of
`ACE Service Installer v4.3.0_424.msi`. Nothing has to be installed: the
files we need are inside the MSI.

## Step 2 — Extract the payloads

An MSI is a compound document (OLE). Extract it with any of:

```console
$ 7z x "ACE Service Installer v4.3.0_424.msi" -omsi   # or: msiextract, or lessmsi
$ 7z x msi/cab1.cab -oapp                             # the embedded cab
```

This yields `app/`, the installed file tree:

* `ACEServiceInstaller.exe`, `ACENetwork.dll`, `ACESettings.dll`, … — the
  .NET assemblies.
* `EDS.xml` — the vendor's own property catalog (CANopen object dictionary):
  id, ParameterName, DataType, AccessType, enumerations, per-language titles.
* `tooltip_en_GB.csv` — the id → label catalog the installer shows in its
  *All Settings* page: `id, OD_name, title, description`. 375 rows, one per
  property the UI knows.
* `InstallerConfigV3.dat` — the installer's encrypted user/feature
  database (see step 4).
* `Lang_Eve_Mini_*.csv` — display strings for the Eve Mini.

## Step 3 — Decompile the assemblies

The assemblies are C#; decompile them with ILSpy:

```console
$ dotnet tool install -g ilspycmd
$ ilspycmd -p -o src app/ACEServiceInstaller.exe        # one project per assembly
$ ilspycmd -p -o src app/ACENetwork.dll                 # repeat per DLL of interest
$ ilspycmd -p -o src app/ACESettings.dll
```

~240 C# files come out of the main assembly. The ones that matter:

* `ACEServiceInstaller/ICUServiceInstaller/Panel*.cs` — one file per settings
  page; every control names the property it edits.
* `ACENetwork/ICUNetwork/ICULanDevice.cs` — the HTTP client: REST paths,
  the login flow, `GetProperty*(propId, subId)`, `SendCommand`,
  firmware upload, `UpdateProperties`.
* `ACESettings/ICUSettings/EDSParser.cs` — how `EDS.xml` is parsed
  (note: it parses the `sub` suffix as hex, but some entries are decimal —
  trust code semantics over the file when they disagree).
* `ACEServiceInstaller/ICUServiceInstaller.Enums/E*.cs` — every enumeration
  the UI can display (states, connector types, security profiles, …).

## Step 4 — Decrypt InstallerConfigV3.dat

`File.ReadAllText` → base64 → AES-256-CBC. Key from
`PasswordDeriveBytes("Pas5pR@sE", "s@1tVaLue", "SHA1", 2)`, IV
`"@1B2c3D4e5F6g7H8"` — all constants in
`ACESettings/ICUSettings/EncryptDecrypt.cs` and `ICUConfig.cs:335`. The
result is a JSON document (`Type: ICUConfigFile`) with `Features` (which
property ids appear on which page), `Groups`, and `Users` (already
SHA-256-hashed per `ICUUser.CreateHashedUser` — the installer's *own* user
accounts, not charger credentials). The decrypted JSON is the `config.json`
cited as `CFG:` evidence in the findings.

## Step 5 — Read the property ids out of the code

Two encodings appear, and the decoding rules are the crux:

1. **Decimal pairs.** `GetProperty*(8273, 0)`, `AddReadOnlyText(8273, 0)` —
   the first argument is the property id in *decimal* (8273 = `0x2051`),
   the second the sub-id (the tooltip file keys write it in *hex*).
2. **Packed uint keys.** `AddCustomSelect(2127616u, …)` in the panels and
   `UpdateProperties(2122752u, …)` in the client: the key is
   `(propId << 8) | subId` (`0x207700` → `2077_00`).

So the mining loop is: grep the decompiled tree for
`GetProperty|HasProperty|Add[A-Za-z]+\(\d+|UpdateProperties\(`, decode each
decimal per the rules above, and record `Panel*.cs:line` as the evidence.
Cross-check every id against `tooltip_en_GB.csv` (`TT:line`), `EDS.xml`
(`EDS:line`), and `config.json` (`CFG:line`).

## Step 6 — Corroborate

* Poll a live charger with the app and a proxy, or just read
  `ICULanDevice.cs` (`ParseProperty`, `UpdatePropertiesInternal`) for the
  REST shapes: `GET /api/prop?ids=…`, `POST /api/prop`, per-property
  `id`/`value`/`type` (SDT codes, `SDT.cs`)/`access`/`cat` fields.
* The EDS `sub` suffix ambiguity (hex vs decimal) resolves by asking the
  charger for both candidates and seeing which answers.

Everything above landed in [`windows-findings.md`](windows-findings.md):
the decoding rules, the master id table with per-row evidence, the enum
maps, unit and type hints, multi-sub object layouts, and the write-only /
read-only / one-way access notes.
