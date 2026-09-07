"""Firmware images: parsing, compatibility rules, and update-status vocabulary.

Mirrors the checks the Windows app performs before an upload -- the file
extension must match the charger family, the filename carries the version,
and crossing the 5.0 firmware boundary requires a new unique per-charger
password -- plus one structural check the app leaves to the device: the
160-byte Alfen container header and its CRC32.

It also parses Alfen's release-file naming ("NG9xx 7.4.5-4415.fwi",
"AHWP01_RELEASE_1.1.1-NFC.tfw"), which is how :mod:`alfenctl.repo` tells
which of the images published on Alfen's server belong to the charger in
front of us.

Finally, it defines the charger's firmware-update status codes
(``ICUNetwork.EFirmwareUpdateStatus``) that
:func:`alfenctl.upgrade.poll_until_done` follows through the
install and reboot.
"""

from __future__ import annotations

import fnmatch
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

# --- Firmware versioning ---------------------------------------------------------------

# A version is major.minor.patch.
VERSION_PART_COUNT = 3
# The app maps an "X" version component (wildcard) to 99.
UNKNOWN_VERSION_COMPONENT = 99
# Crossing major version 5 requires a new unique per-charger password
# (the "5.0 barrier").
FW_MAJOR_5_BOUNDARY = 5
# NG9xx chargers below 6.6 should be taken to 6.6.2 before 7.x: the app shows
# exactly this in red on its upload dialog (DlgUpload.ShowNg9xxUpgradeWarning).
NG_STEPPING_STONE_BELOW = (6, 6)
NG_STEPPING_STONE_MAJOR = 7
NG_STEPPING_STONE_RELEASE = "6.6.2"

# --- Alfen firmware container header ----------------------------------------------------

# Both a core .fwi (shipped by Alfen) and an ACEFWUCreator .fwu display package
# start with the same 160-byte header we can structurally validate before
# upload: u32 CRC32 (over the following 156 bytes), u32 header length (== 160),
# u32 magic, ...
# The upper 3 bytes of the magic (0xA1FE00) are the stable Alfen marker; the
# low byte is a type/variant code (0x13 for a .fwu package, 0x21 for a core
# .fwi), so we match the prefix only. The remaining header fields differ by
# firmware type, so we rely on the CRC for integrity rather than checking them.
FWI_HEADER_LEN = 160
FWI_LEN_OFFSET = 4  # u32 header-length field, expected to equal FWI_HEADER_LEN
FWI_MAGIC_OFFSET = 8  # the u32 magic sits 8 bytes into the header
FWI_MAGIC_PREFIX = 0xA1FE00  # upper 3 bytes of the magic (magic >> 8)
FWI_CRC_OFFSET = 0  # the u32 CRC32 sits at the very start
FWI_CRC_START = 4  # ...and is computed over header bytes [FWI_CRC_START:FWI_HEADER_LEN)
MAGIC_LOW_BYTE_BITS = 8  # shift to drop the magic's variant low byte
U32_MASK = 0xFFFFFFFF  # mask zlib.crc32's result to an unsigned 32-bit value

# --- Firmware update state machine (ICUNetwork.EFirmwareUpdateStatus) --------------------

FW_NO_ACTIVE_UPDATE = 0
FW_UPDATE_DONE = 10
# Full label map, used for logging the charger's reported status.
FW_STATUS = {
    0: "NO_ACTIVE_UPDATE",
    1: "ERASING_BUFFER",
    2: "BUFFER_ERASED",
    3: "READY_FOR_DOWNLOAD",
    4: "DOWNLOADING_FIRMWARE",
    5: "DOWNLOAD_DONE",
    6: "DOWNLOAD_CHECKED",
    7: "READY_FOR_UPDATE",
    8: "UPDATE_IN_PROGRESS",
    9: "UPDATE_READY_TO_ROLL",
    10: "UPDATE_DONE",
    11: "CRC_CALCULATING",
    12: "CRC_CALCULATED",
    -1: "ERROR_DURING_DOWNLOAD",
    -2: "ERROR_DURING_UPDATE",
    -3: "EXECUTING_ROLLBACK",
    -4: "ROLLED_BACK",
}
# Terminal states: download/update errors and rollbacks (failure), and idle or
# done (success).
FW_TERMINAL_ERR = frozenset({-1, -2, -3, -4})
FW_TERMINAL_OK = frozenset({FW_NO_ACTIVE_UPDATE, FW_UPDATE_DONE})


def parse_fw_version(raw: str) -> tuple[int, int, int] | None:
    """Parse "5.6.1-4183" into ``(5, 6, 1)``.

    An "X" component becomes :data:`UNKNOWN_VERSION_COMPONENT`, as the app does.
    Return ``None`` if the string is not a dotted version.
    """
    head = raw.split("-", 1)[0].replace("X", str(UNKNOWN_VERSION_COMPONENT))
    parts = head.split(".")
    if len(parts) < VERSION_PART_COUNT or not all(
        p.isdigit() for p in parts[:VERSION_PART_COUNT]
    ):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def device_family(model: str) -> str:
    """Return the firmware family for ``model``: "AHP" or "NG".

    AHP/AHWP chargers form one family (.tfw/.tcf); everything else
    (NG9xx/Eve/Twin/Tube) is the other (.fwi/.fwu). Mirrors
    ``ICULanDevice.isAHP`` / ``getUpdateFileTypes``.
    """
    m = model.upper()
    return "AHP" if m.startswith("AHP") or m.startswith("AHWP") else "NG"


# Extensions of every firmware image the app knows, and the extension of the
# .zip release bundle Alfen ships an image in (image + certificate + signature
# + OCPP key list).
ALL_FIRMWARE_EXTENSIONS = (".fwi", ".fwu", ".tfw", ".tcf", ".tvf")
BUNDLE_EXTENSION = ".zip"


def allowed_extensions(family: str) -> tuple[str, ...]:
    """Return the firmware file extensions allowed for a charger ``family``."""
    return (".tfw", ".tcf") if family == "AHP" else (".fwi", ".fwu")


# --- Release-file naming ----------------------------------------------------------------

# Alfen names a release "<product><sep><major.minor.patch>[-<build>][-<variant>]",
# e.g. "NG9xx 7.4.5-4415.fwi", "NG9xx 5.8.1-4123-A.fwi",
# "AHWP01_RELEASE_1.1.1-NFC.tfw", "ng910v1.2.5-1737.fwi". The separator before
# the version is a space, an underscore or a bare "v"; DlgUpload's own regex
# ("[_ ](\d+.\d+.\d+)[_.-]") accepts only the first two, so it reads no
# version at all from the older "ng910v..." names.
_RELEASE_NAME_RE = re.compile(
    r"^(?P<product>.*?)[ _v-]*"
    r"(?P<version>\d+\.\d+\.\d+)"
    r"(?:\s*-\s*(?P<build>\d+))?"
    r"(?P<variant>.*)$"
)
# A product code is the leading letters+digits of the name ("NG9xx",
# "AHWP01_RELEASE" -> "AHWP01"); the same shape identifies the charger's model
# ("NG910-60027" -> "NG910").
_PRODUCT_CODE_RE = re.compile(r"[A-Za-z]+[0-9A-Za-z]*")


@dataclass(frozen=True)
class ReleaseName:
    """What Alfen's release-file naming tells us about an image.

    ``product`` is the product code the file is built for ("NG9xx", "AHWP01"),
    ``version``/``build`` the release it carries, and ``variant`` any trailing
    hardware/feature qualifier ("-A", "-NFC").
    """

    product: str
    version: tuple[int, int, int] | None
    build: int | None
    variant: str

    @property
    def label(self) -> str:
        """Return the version as Alfen writes it, e.g. "7.4.5-4415"."""
        if self.version is None:
            return ""
        v = ".".join(map(str, self.version))
        return f"{v}-{self.build}" if self.build is not None else v


def strip_firmware_suffix(name: str) -> str:
    """Drop a firmware/bundle extension from ``name``, leaving other dots alone.

    ``Path.suffix`` is no use here: the version itself is dotted, so
    "NG9xx 4.14.0-3398-A" would lose "-3398-A" with it.
    """
    for ext in (*ALL_FIRMWARE_EXTENSIONS, BUNDLE_EXTENSION):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


def parse_release_name(name: str) -> ReleaseName:
    """Split a firmware file name into product, version, build and variant.

    Any part that is not present comes back empty/``None``; a name that
    carries no version at all yields ``ReleaseName(name, None, None, "")``.
    """
    stem = strip_firmware_suffix(name.rsplit("/", 1)[-1])
    m = _RELEASE_NAME_RE.match(stem)
    if m is None:
        return ReleaseName(stem.strip(" _-"), None, None, "")
    return ReleaseName(
        product=m["product"].strip(" _-"),
        version=parse_fw_version(m["version"]),
        build=int(m["build"]) if m["build"] else None,
        variant=m["variant"].strip(" _-"),
    )


def product_code(text: str) -> str:
    """Return the leading product code of ``text``, upper-cased ("" if none)."""
    m = _PRODUCT_CODE_RE.match(text.strip())
    return m[0].upper() if m else ""


def product_matches_model(product: str, model: str) -> bool:
    """Return whether a release's ``product`` covers a charger ``model``.

    Alfen writes an "x" where a digit varies, so the NG9xx images cover
    NG900/NG910/NG920 while an AHWP01 image does not cover an AHP02. Both
    sides are reduced to their product code first, so "NG910-60027" is
    compared as "NG910".

    The release side is also a prefix: Alfen ships the Eve/AHP line as
    "AHP_release_FW_2.5.0_FULL.tfw", whose product code is the bare "AHP"
    even though the chargers it serves call themselves AHP02 or AHPDC.
    Anchoring only the start keeps that pairing while still holding
    "NG910" apart from an NG920 and "AHWP01" apart from an AHP02.
    """
    want, have = product_code(product), product_code(model)
    if not want or not have:
        return False
    return fnmatch.fnmatchcase(have, want.replace("X", "?") + "*")


def needs_stepping_stone(
    family: str,
    current_version: tuple[int, int, int] | None,
    target_version: tuple[int, int, int] | None,
) -> bool:
    """Return whether an NG9xx jump needs :data:`NG_STEPPING_STONE_RELEASE` first.

    Alfen asks that NG9xx chargers below 6.6 be taken to 6.6.2 before 7.x;
    the app shows this as a standing red warning whenever the charger is
    below 6.6, we raise it only for the jumps it actually applies to.
    """
    if family != "NG" or current_version is None or target_version is None:
        return False
    return (
        current_version[:2] < NG_STEPPING_STONE_BELOW
        and target_version[0] >= NG_STEPPING_STONE_MAJOR
    )


@dataclass
class FirmwareFile:
    """A firmware file on disk plus the family/version we can infer from it.

    Mirrors the checks the Windows app performs before an upload: extension by
    family, filename version, and the Alfen container header CRC.
    """

    path: Path
    data: bytes
    version: tuple[int, int, int] | None
    is_alfen_container: bool  # True when the file starts with a recognised Alfen header
    header_ok: bool | None  # header CRC validity; None when not an Alfen container

    @classmethod
    def load(cls, path: Path) -> "FirmwareFile":
        """Read the file and infer its version and container/header validity."""
        data = path.read_bytes()
        # Filename version regex from DlgUpload.OnBtnUploadClicked:
        # "[_ ](\\d+.\\d+.\\d+)[_.-]".
        m = re.search(r"[_ ](\d+)\.(\d+)\.(\d+)[_.\-]", path.name.lower())
        version = (int(m[1]), int(m[2]), int(m[3])) if m else None
        header_ok: bool | None = None
        is_container = cls._looks_like_alfen_header(data)
        if is_container:
            # The header CRC32 is stored at FWI_CRC_OFFSET, over bytes
            # [FWI_CRC_START:len).
            want = struct.unpack_from("<I", data, FWI_CRC_OFFSET)[0]
            got = zlib.crc32(data[FWI_CRC_START:FWI_HEADER_LEN]) & U32_MASK
            header_ok = got == want
        return cls(path, data, version, is_container, header_ok)

    @staticmethod
    def _looks_like_alfen_header(data: bytes) -> bool:
        """Return whether ``data`` starts with an Alfen firmware container header.

        We require the 160-byte header-length field and the Alfen magic prefix;
        the exact magic low byte and the later fields vary between core .fwi
        and .fwu packages, so we leave the actual integrity check to the CRC.
        """
        if len(data) < FWI_HEADER_LEN:
            return False
        header_len = struct.unpack_from("<I", data, FWI_LEN_OFFSET)[0]
        magic = struct.unpack_from("<I", data, FWI_MAGIC_OFFSET)[0]
        return (
            header_len == FWI_HEADER_LEN
            and (magic >> MAGIC_LOW_BYTE_BITS) == FWI_MAGIC_PREFIX
        )


@dataclass
class CompatResult:
    """Outcome of the pre-upload compatibility check: errors block, warnings/notes inform."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def check_compatibility(
    family: str,
    current_version: tuple[int, int, int] | None,
    fw: FirmwareFile,
) -> CompatResult:
    """Check that ``fw`` suits a charger of ``family`` running ``current_version``.

    Replicates (and slightly extends) the pre-upload checks the Windows app
    performs:

    * the file extension must match the charger family
      (AHP -> .tfw/.tcf, else -> .fwi/.fwu);
    * an NG9xx crossing the 5.0 boundary needs a new unique per-charger
      password (set one with ``--new-password`` during the upgrade);
    * an NG9xx below 6.6 should be taken to 6.6.2 before 7.x (the app shows
      this as a standing warning; we raise it for the jumps it applies to);

    plus a structural check the app trusts the device with:

    * if the file has an Alfen container header, its 160-byte header CRC32
      must validate.
    """
    res = CompatResult(ok=True)
    ext = fw.path.suffix.lower()
    allowed = allowed_extensions(family)
    if ext not in allowed:
        res.ok = False
        res.errors.append(
            f"file extension '{ext}' does not match a {family}-family charger "
            f"(expected {', '.join(allowed)})"
        )

    if fw.is_alfen_container and fw.header_ok is False:
        res.ok = False
        res.errors.append(
            "firmware container header CRC32 is invalid — "
            "file is corrupt or not an Alfen image"
        )

    tgt = fw.version
    if tgt is None:
        res.warnings.append(
            "could not read a version from the filename; cannot compare against the charger"
        )
    elif current_version is not None:
        cur = current_version
        res.notes.append(
            f"charger {'.'.join(map(str, cur))} -> file {'.'.join(map(str, tgt))}"
        )
        if family == "NG" and cur[0] < FW_MAJOR_5_BOUNDARY <= tgt[0]:
            res.warnings.append(
                "crossing the 5.0 firmware boundary: the charger will require a NEW unique "
                "password afterwards (pass --new-password to set it during the upgrade)"
            )
        if needs_stepping_stone(family, cur, tgt):
            res.warnings.append(
                "Alfen asks that an NG9xx below 6.6 be taken to "
                f"{NG_STEPPING_STONE_RELEASE} before {NG_STEPPING_STONE_MAJOR}.x"
            )
        if tgt < cur:
            res.warnings.append(
                "target version is OLDER than the charger's current firmware (downgrade)"
            )
    return res
