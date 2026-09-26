# Firmware formats, update flow, and diagnostic interfaces

## Scope and sources

These findings describe NG9xx firmware containers, the client-side update
flow, console dispatch, and diagnostic interfaces. They are based on local
vendor client archives, public firmware packages, and a captured NG910 log,
reviewed on 2026-09-08. Package analysis was performed offline; no firmware
was installed as part of that analysis.

Client behavior, package structure, and station observations are documented
separately. A command in a client catalog does not establish support or
authorization on every firmware version. In reported NG910-60027 operation,
`flash-info` and `flash-dump` produced no observable action or log output.

## Console command transport

MyEve 2.3.1 sends console command strings through the default station API:

```text
POST https://<station-ip>[:port]/api/cmd
{"command":"flash-info"}

POST https://<station-ip>[:port]/api/cmd
{"command":"flash-dump"}
```

The source Hermes bundle is 8,464,452 bytes, version 96, SHA256
`343005158d1b85792de89d9e812f64630f6790cbd4da47d1a12718f4a206a1fb`.
Its archive path is
`research/android/MyEve+-+Alfen_2.3.1_APKPure.xapk` →
`com.alfen.myeve.apk` → `assets/index.android.bundle`.

| Function | Behavior |
| --- | --- |
| #29352, `0x67594a` | Maps `flashmemoryInfo` to `flash-info` and `flashmemoryDump` to `flash-dump` |
| #29357, `0x675d7b` | Calls `station.api.executeCommand(state.trim())` |
| #20566 / #20790 | Constructs the default station API as `CsApi(new CsHttpClient(station))` |
| #20699, `0x585a04` | Posts `{endpoint: "/cmd", data: {command: argument}}` |
| #22704 / #22705 | Builds the URL and submits the POST body through `session.withLogin` |
| #22706, `0x5abfa9` | Builds the URL as `station.baseUrl + "/api" + endpoint` |
| #20578, `0x583677` | Builds the base URL from `https://`, the station IP, and an optional port |

The `{command, csName}` object in #29357 is notification-formatting data,
stored separately from the command string passed to the API. The default
dispatch path sends the selected literal without additional parameters or
AHP/NG translation. The station class also accepts an injected API factory;
the trace above describes the default implementation.

Windows `research/windows/src/ACENetwork/ICUNetwork/ICULanDevice.cs:2623-2625`
likewise sends the supplied command unchanged to `/api/cmd`.
`DlgCommand.cs:56-62` uses the existing session without a separate console
login sequence. MyEve #20699 discards the resolved response and returns
undefined. Its success notification therefore indicates submission rather
than command-handler output.

### Command availability and station login roles

MyEve #29363 (`0x67627e`) enables the advanced command choices when:

```text
firmwareVersionHasPasswordSupport(station.isAHP, station.firmwareVersion)
&& station.LoginType === ChargingStationUserType.SSA
```

`LoginType` is the station's selected login role: #20605 returns
`loginUserType`. It is separate from the cloud-account role. When access is
limited, #29360 retains four commands: `forcefirmwarepermanent`, `reboot`,
`txerase`, and `eepromx erase config`. The flash commands are outside this
set. The client-side filter and server-side authorization are separate.

For an HTTP session, #22686 calls
`getCSApiCredentials(identifier, loginUserType)`. #11518 reads the stored
credentials from temporary storage and reports an error if they are absent.
#22716 submits them to `/api/login`. Windows
`DlgDeviceLogin.cs:69-98,234-245` similarly distinguishes owner/admin,
temporary, and service/SSA credentials and requires a supplied password.

### Captured command and authorization events

`research/artifacts/ACE0781464.log` records:

- Lines 970–975: web `Executing command: 'date ...'`, followed about
  0.43 seconds later by `users.c:403:Invalid password (service)`.
- Lines 44–48 and 17: web `date ...`, followed about 0.42 seconds later
  by `taskCommandLine.:34:Incorrect password`.
- Lines 735–736: `Executing: system(cansync off)` and a `CONSOLE` record
  during an update, without a corresponding user web request.

The capture contains out-of-order ring-buffer chunks and repeated historical
events, so repeated entries are not independent observations. It does not
include the reported `flash-info` and `flash-dump` submissions.

[INFERENCE] The timing of the password errors is consistent with a
command-level service authorization check in addition to HTTP login.
The capture does not establish the check's implementation or which flash
command handlers this firmware supports. The client dispatch code does not
check charging/idle state or enter a service mode; firmware-side conditions
are not described by that client code.

## Update, security, and diagnostic interfaces

Paths in this table are relative to `research/windows/`.

| Interface | Documented behavior and source |
| --- | --- |
| Firmware encryption-key property `0x2713` | `app/EDS.xml:2906-2911` defines `securityFirmwareUpdateEncryptionKey` as a write-only DOMAIN object. |
| Diagnostics key `0x2712` | `app/EDS.xml:2900-2905` defines a write-only object associated with Get Diagnostics. |
| Firmware public key `0x2714` | `app/EDS.xml:2912-2917` defines a read/write signature-validation public key. |
| `/api/domain`, item type 4 | `ICUDomain.cs:18-27` and `EDomainItemType.cs:5-11` define provisioning of caller-supplied bytes with `cmd: "add"`. Changes affect firmware-update configuration. |
| `GET /api/firmware` | `ICULanDevice.cs:2446-2481` reads update state. EDS `0x2912` is upload-only; `0x2915` returns a buffer CRC. |
| `/api/diagtool` | `ICULanDevice.cs:2660-2675,2731-2785` implements diagnostic submission and result retrieval, described below. |
| EDS `0x2903` | Defines binary diagnostics retrieval metadata; its payload format and HTTP mapping are not specified by the inspected code. |
| `/api/prop`, `/api/log` | Provide property values and text log records. The 314-row property capture contains no `2711`–`2714` records. |
| Property `3182_0` | Reports the bootloader version. CAN-related EDS object names describe metadata, not a client CAN/SDO transport implementation. |

EDS declarations describe the vendor object model, not the availability of
every object on each firmware build. A property's absence from a captured
response only describes that response.

### Diagnostic request and result lifecycle

Diagnostics use a separate endpoint from console commands. The Windows
client submits a command name, a byte-sized sequence ID represented as a
JSON string, and an ordered array of numbered string parameters:

```text
POST /api/diagtool
{"command":"<diagnostic-name>","sequenceID":"7","parameters":[{"param0":"<value>"}]}

GET /api/diagtool?result
```

With no parameters, `parameters` is an empty array. The result reader
accesses the response version and `DiagnosticResult` fields `command`,
`sequenceid`, `finished`, and `result`. Field spelling and values, including
string-valued flags and firmware-specific fields, are preserved by alfenctl.

Submission and completion are separate: the current result may describe an
earlier command or an operation still in progress. Match its command and
sequence ID and inspect `finished` before interpreting the result.
`alfenctl diag result` reads once without polling. Diagnostic names,
parameter meanings, and result formats are firmware-specific; the inspected
clients implement the transport without a diagnostic command catalog.
Diagnostic operations may change station state and remain subject to
station authorization.

### Firmware upload flow

Windows `ICULanDevice.cs:2398-2401` reads the complete FWI file and calls
`StartUpload`; line 2153 submits the bytes to `/api/firmware`.
Lines 1170–1192 apply multipart framing, with 4096-byte parts for HTTPS.
The client transfers the firmware container unchanged; package processing
occurs on the station.

## NG9xx firmware container

The inspected `NG9xx 7.4.5-4415.fwi` has:

- SHA256 `0af6c6fce70a9f4bf0e768c0fb7e97cace6f04420483da4404e71df81c39454f`;
- a 160-byte header with CRC32 `0x13038f60` over bytes `[4:160]`;
- little-endian magic `0xa1fe0021` at offset 8;
- a little-endian payload length of 1,818,880 at offset 20;
- total size 1,819,296 = 160-byte header + 1,818,880-byte payload +
  256-byte trailer.

The captured update log identifies `AES128`,
`PKCS1_PSS_SHA256_2048`, and `UPDATE_FIRMWARE_NG9xx_VERSION_01`.
The detached Base64 `-sig.txt` signature validates `fwi[:-256]` with the
accompanying RSA-2048 certificate, SHA256/PSS/MGF1-SHA256, and salt length 32.
The embedded 256-byte trailer differs from the detached signature and did
not validate with the same certificate, message, and scheme. Its role
remains unspecified.

### Package inventory and compatibility

Four older NG images are included in the MyEve APK's
`assets/backendAssets/`. Public vendor archives provide the additional
6.6.2 A/B bootloader updates and 4.12 package listed below.

| Image | Source | File bytes | Payload bytes |
| --- | --- | ---: | ---: |
| 7.4.5-4415 | Local release package | 1,819,296 | 1,818,880 |
| 7.2.0-4362 | APK | 1,806,160 | 1,805,744 |
| 7.1.6-4345 | APK | 1,809,424 | 1,809,008 |
| 6.6.2-4312-BL-upgrade-B | APK | 978,944 | 978,528 |
| `5.6.0-4104-B .fwi` (space before extension) | APK | 978,832 | 978,416 |
| 6.6.2-4396-BL-upgrade-A | Vendor KA-01416 | 978,944 | 978,528 |
| 6.6.2-4396-BL-upgrade-B | Vendor KA-01416 | 978,944 | 978,528 |
| 4.12.0-3320 | Vendor KA-01609 | 959,344 | 958,928 |

The first seven packages passed header CRC validation and contained no
repeated aligned 16-byte payload blocks. Their payload byte entropy was
approximately 7.9998–7.9999 bits/byte; the 4.12 payload measured approximately
7.9998 bits/byte. Entropy alone does not identify a cipher or its mode.
Detached signatures for the public 6.6.2 A/B and 4.12 packages validated
with their respective certificates using the PSS scheme above. The public
6.6.2 A/B payloads shared no identical aligned ciphertext blocks.

Vendor compatibility guidance distinguishes encryption variants A and B:
A applies to 4.12 and older, B to 4.14 onward, and distribution is B-only
from 7.0. Supported update paths can require intermediate releases;
downgrade compatibility depends on the installed version. The 6.6.2 A/B
packages include a bootloader update.

## Related formats and cryptographic roles

Display resources, SCN telemetry, and executable firmware use distinct
processing paths. Windows
`src/ACEFWUCreator/ICUFWUCreator/ICUFWUCreator.cs:37-100,301-322`
defines the display-resource format as follows:

```text
Cipher:         AES-128-CBC with a fixed resource key
IV:             00000000000000000000000000000000
Padding:        PKCS#7
Inner framing:  LE32 CRC32, LE32 total-inner-length, LE32 0, LE32 0, data
CRC coverage:   inner bytes [4:total-inner-length]
```

This describes display-resource packaging, not the NG9xx executable payload
format. `SCNNetwork.cs:28-32,66-80` implements a separate AES-based path for
UDP telemetry. Station login credentials and TLS certificates serve session
authentication and transport security. The inspected client code does not
specify the NG9xx executable payload's AES mode, IV construction, or internal
layout.

The APK also includes the 45,389,658-byte
`AHP_release_FW_2.1.0_FULL.tfw`. Its front matter contains readable manifest
and certificate text, and an OpenSSL-style `Salted__` marker occurs at
offset 1434. The marker alone does not specify the cipher. The inspected
file had no ELF, SquashFS, ZIP, or XZ signature matches; three gzip magic
matches did not form valid gzip streams.

## Reproduction and primary sources

The [Android guide's bytecode example](../android/android-guide.md#reproduce-the-console-trace-from-the-shipped-xapk)
reproduces the client dispatch trace. The recorded run covered 16 functions
and produced 880 disassembly lines. The
[Android findings](../android/android-findings.md#console-command-map-and-concrete-transport)
describe the register-level interpretation. Package measurements and
signature checks used Python `zipfile`, `struct`, `zlib`, and `cryptography`.
Vendor archives and generated analysis artifacts remain local rather than
being included in the repository.

- [Alfen A/B firmware compatibility](https://aceservice.alfen.com/en-us/knowledgebase/article/KA-01186):
  version boundaries for A/B variants and B-only distribution.
- [Alfen NG update paths](https://aceservice.alfen.com/en-us/knowledgebase/article/KA-01244):
  intermediate releases and downgrade-compatibility guidance.
- [Alfen 6.6.2 bootloader-upgrade A/B archive](https://aceservice.alfen.com/en-us/knowledgebase/article/KA-01416):
  packages that include the bootloader update.
- [Alfen 4.12 archive](https://aceservice.alfen.com/en-us/knowledgebase/article/KA-01609):
  the older A-variant release in the package inventory.
