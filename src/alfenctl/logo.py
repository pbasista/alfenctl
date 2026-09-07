"""Splash-screen logo upload (the app's DlgUploadResources + FWU/TVF creators).

The vendor app has no dedicated logo endpoint: it converts the image, packs
it into a container, and ships it through the same ``POST /api/firmware``
multipart channel as a firmware image, with none of the follow-up (no status
polling, no ``forcefirmwarepermanent`` -- the device applies it on its own).

Two container formats, by charger family:

* **NG** (NG9xx / Eve / Twin, the ``.fwi`` firmware family): a ``.fwu``
  package -- an object stream (customer logo as PALETTED8 + the device's
  fixed L1 status icons and Robotica fonts, all embedded verbatim from the
  app's ``ICUObjects.cs``), wrapped in a CRC'd ``.bin``, AES-128-CBC
  encrypted (the app's hardcoded key, zero IV), behind the 160-byte FWI
  header with magic ``0xA1FE0013`` (``ICUFWUCreator.CreateFWUData``).
* **AHP**: a ``.tvf`` package -- a CRC'd header (magic ``0xB90F0F55``)
  followed by ``gzip(tar(logo.png + manifest.json + videoresources.json))``
  (``ICUTVFCreator.CreateTvfData``). PNG input only, max 500 kB total.

Image conversion mirrors the app's ``ICULogoConvertor.ConvertImage``
(decompiled): composite onto white, scale *covering* the target box (the
larger axis ratio, floored -- the box keeps the display's aspect), then
quantize to <=128 colors (the app uses Xiaolin Wu's algorithm; Pillow's
median-cut is a close stand-in that only affects looks, not acceptance --
palette size and dimensions are enforced port-side either way).

Display limits come from properties ``12896_3``/``12896_4`` (max logo
width/height), defaulting to 320x160 (800x350 counts as a large screen and
adds the third font object).

Not every station has a screen at all, and one that has none takes the
upload and does nothing with it.  :func:`read_display` mirrors the app's
``ICULanDevice.HasDisplay``: the display descriptor ``0x3260`` sub 1 exists
and its max logo width and height are both positive, or the model is one the
app knows has a fixed display anyway (Eve Mini, NG910-60014, NG910-60034) or
a dual-plug NG920.  Its own dialog greys the upload button out and says "The
current selected device does not have a display", which is what
``alfenctl logo`` and the web UI now do -- with ``--force`` to send it
regardless, since only the charger can settle what it really does with it.
"""

from __future__ import annotations

import binascii
import io
import json
import struct
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from alfenctl.charger import AlfenCharger
from alfenctl.errors import AlfenError
from alfenctl.values import as_int

# --- Device limits (DlgUploadResources / ICULanDevice) --------------------------------------

DEFAULT_LOGO_SIZE = (320, 160)  # (MaxLogoWidth, MaxLogoHeight) fallback
LOGO_MARGIN = 8  # default margin on each side (DlgUploadResources)
MAX_COLORS = 128  # s_nMaxColors (DlgUploadResources)
LARGE_SCREEN_WIDTH = 320  # wider displays get font_robotica_30 too
PROP_DISPLAY_INFO = (0x3260, 0)  # 12896_0: display descriptor (w/h at sub 3/4)
PROP_DISPLAY_PRESENT = (0x3260, 1)  # 12896_1: the sub the app tests for at all
PROP_LOGO_WIDTH = (0x3260, 3)  # 12896_3
PROP_LOGO_HEIGHT = (0x3260, 4)  # 12896_4

# Models with a screen the firmware does not describe.  The app carries the
# same two lists: ICULanDevice.IsOldModelWithDisplay and IsDualPG.
OLD_MODELS_WITH_DISPLAY = ("NG910-60014", "NG910-60034")
DUAL_PG_MODELS = tuple(f"NG920-6200{n}" for n in range(1, 6))
MODEL_CODE_LEN = 11  # "NG910-60014", the width the app compares on

# --- FWU container constants (ICUFWUCreator / ICUObjectTypes / ICUImageFormats) --------------

OBJECT_LOGO_CUSTOMER = 0
OBJECT_LOGO_ACCEPTED = 1
OBJECT_LOGO_CHARGING = 2
OBJECT_LOGO_SOCKETERROR = 3
OBJECT_LOGO_COMMUNICATING = 4
OBJECT_ROBOTICA_28 = 5
OBJECT_ROBOTICA_29 = 6
OBJECT_ROBOTICA_30 = 8

FORMAT_L1 = 1
FORMAT_L4 = 2
PALETTED8 = 16

FWU_MAGIC = 0xA1FE0013  # .fwu variant of the firmware header magic
FWU_FILE_TYPE = 0xA201  # (ushort)41473 in CreateFWIHeader; the parser
# dispatches on this word (charger log: "Unexpected UpdateFirmware file
# type") -- 0xA1E1 was a decimal->hex mistranscription and got rejected.
FWU_HEADER_LEN = 160  # u32 header length field, and the header's size
FWU_FILLER_U32S = 32  # trailing 0xFFFFFFFF filler words
FWU_HEADER_FIXED = struct.pack(
    "<IIIIHHII", 0, 160, FWU_MAGIC, 0xFFFFFFF7, FWU_FILE_TYPE, 39, 0, 0
)  # everything before dataLength in CreateFWIHeader (CRC patched later)

# The app's AES-128 key (ICUFWUCreator.AESEncrypt), zero IV, CBC/PKCS7.
FWU_AES_KEY = bytes(
    [41, 198, 106, 32, 174, 22, 196, 186, 4, 106, 33, 213, 122, 120, 102, 79]
)

# Object-record fixed fields (AddObjectToStream): the 32-byte head is
# followed by the palette (if any) and the deflated payload.
RECORD_HEAD_LEN = 32


# Fixed device assets: the status icons and Robotica fonts every package
# carries besides the customer logo, lifted verbatim from the app's
# ``ICUObjects.cs``.  ``logo_blobs.bin`` is their plain concatenation, in
# this order, which is why each one records its own length -- there is
# nothing in the file to find a boundary by.  ``tools/extract_assets.py``
# rebuilds the file from the decompiled source and checks it against this.
@dataclass(frozen=True)
class FixedObject:
    """One embedded device asset: how to describe it, and where it is."""

    object_type: int
    fmt: int
    width: int
    height: int
    stride: int
    vertical_offset: int
    name: str  # its variable name in ICUObjects.cs
    blob_bytes: int  # its length in logo_blobs.bin


FWU_FIXED_OBJECTS = (
    FixedObject(OBJECT_LOGO_ACCEPTED, FORMAT_L1, 56, 59, 7, 0, "logo_accepted_L1", 413),
    FixedObject(
        OBJECT_LOGO_CHARGING, FORMAT_L1, 80, 50, 10, 0, "logo_charging_L1", 500
    ),
    FixedObject(OBJECT_LOGO_SOCKETERROR, FORMAT_L1, 56, 56, 7, 0, "logo_error_L1", 392),
    FixedObject(
        OBJECT_LOGO_COMMUNICATING, FORMAT_L1, 56, 78, 7, 0, "logo_communicating_L1", 546
    ),
    FixedObject(
        OBJECT_ROBOTICA_28, FORMAT_L4, 20, 28, 10, -2, "font_robotica_28", 18068
    ),
    FixedObject(
        OBJECT_ROBOTICA_29, FORMAT_L4, 22, 30, 11, -2, "font_robotica_29", 21268
    ),
    FixedObject(
        OBJECT_ROBOTICA_30, FORMAT_L4, 30, 41, 15, -4, "font_robotica_30", 39508
    ),
)

# Where the concatenated blobs live, next to this module.
BLOB_FILE = "logo_blobs.bin"

# --- TVF container constants (ICUTVFCreator / TvfHeader) --------------------------------------

TVF_MAGIC = 3102571221  # 0xB90F0F55
TVF_BASE_HEADER_LENGTH = 1350
TVF_MAX_BYTES = 500 * 1024


class LogoError(AlfenError):
    """The logo could not be converted or packaged (bad input, too large)."""


@dataclass(frozen=True)
class LogoAsset:
    """A parsed image asset: indexed pixels plus its palette."""

    width: int
    height: int
    indices: bytes  # one palette index per pixel, row-major
    palette: bytes  # RGB triples, 3*n entries


def _fixed_blobs() -> dict[str, bytes]:
    """Slice the packaged blob file into the assets :data:`FWU_FIXED_OBJECTS` names."""
    data = Path(__file__).with_name(BLOB_FILE).read_bytes()
    expected = sum(obj.blob_bytes for obj in FWU_FIXED_OBJECTS)
    if len(data) != expected:
        raise LogoError(
            f"{BLOB_FILE} is {len(data)} bytes, but the object table adds up "
            f"to {expected}; regenerate it with tools/extract_assets.py"
        )
    out: dict[str, bytes] = {}
    at = 0
    for obj in FWU_FIXED_OBJECTS:
        out[obj.name] = data[at : at + obj.blob_bytes]
        at += obj.blob_bytes
    return out


def crc32(data: bytes) -> int:
    """Return the container CRC (reversed poly 0xEDB88320 -- plain binascii)."""
    return binascii.crc32(data) & 0xFFFFFFFF


def _deflate(data: bytes) -> bytes:
    """Return ``data`` in the app's framing: raw DEFLATE behind a 78 9C header."""
    import zlib

    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    return b"\x78\x9c" + co.compress(data) + co.flush()


def convert_image(path: Path, size: tuple[int, int]) -> LogoAsset:
    """Convert an image file to the app's indexed form for a ``size`` box.

    Mirrors ``ICULogoConvertor.ConvertImage``: composite onto white, scale to
    *fit* the box while preserving the aspect ratio (the larger axis ratio
    wins, floored, so one axis fills the box and the other is at most equal;
    small images are upscaled the same way), quantize to <= 128 colors
    without dithering.
    """
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise LogoError(
            "Pillow is required for logo conversion (pip install pillow)"
        ) from exc
    try:
        img = Image.open(path)
        img.load()
    except OSError as exc:
        raise LogoError(f"cannot read image '{path}': {exc}") from exc

    box_w, box_h = size
    scale = max(img.width / box_w, img.height / box_h)
    new_w = max(1, int(img.width // scale))
    new_h = max(1, int(img.height // scale))

    # Composite onto opaque white (alpha flattened), like SetImageBackground.
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img.convert("RGBA"))
    img = img.convert("RGB")

    # LANCZOS ~= GDI+ high-quality bicubic for the downscale.
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    q = img.quantize(
        colors=MAX_COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    # The app always sends a full-size palette: Wu's OnGetPalette builds
    # exactly `colorCount` colors (empty cubes -> black), and ConvertImage
    # keeps 128 entries.  The charger's parser rejects a shorter palette
    # (HTTP 400 on upload), so pad with black to MAX_COLORS entries and
    # always report nColors-1 = MAX_COLORS-1 (AddObjectToStream num6/num7).
    pal = (q.getpalette() or [])[: MAX_COLORS * 3]
    pal_bytes = bytes(pal).ljust(MAX_COLORS * 3, b"\x00")
    return LogoAsset(
        width=new_w,
        height=new_h,
        indices=q.tobytes(),
        palette=pal_bytes,
    )


def _object_record(
    data: bytes,
    object_type: int,
    fmt: int,
    width: int,
    height: int,
    stride: int,
    vertical_offset: int,
    palette: bytes | None,
) -> bytes:
    """One FWU object record (AddObjectToStream), 4-byte aligned.

    For the customer logo the app always passes maxColors as the palette
    count (128), even when the quantized image uses fewer colors; fixed
    objects pass image=null and carry no palette at all.
    """
    comp = _deflate(data)
    n_colors = MAX_COLORS if palette is not None else 0
    object_len = RECORD_HEAD_LEN + n_colors * 3 + len(comp)
    pad = (4 - object_len % 4) % 4
    object_len += pad
    head = struct.pack(
        "<BBHHHIIBBHHhII",
        1,  # version
        object_type,
        width,
        height,
        stride,
        object_len,
        len(comp),
        fmt,
        max(n_colors - 1, 0),
        RECORD_HEAD_LEN if n_colors else 0,
        (RECORD_HEAD_LEN + n_colors * 3) if n_colors else RECORD_HEAD_LEN,
        vertical_offset,
        crc32(data),
        crc32(comp),
    )
    assert len(head) == RECORD_HEAD_LEN, len(head)
    body = (palette or b"") + comp + b"\x00" * pad
    return head + body


def _aes_encrypt(data: bytes) -> bytes:
    """AES-128-CBC/PKCS7 with the app's key and zero IV (stdlib only)."""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise LogoError(
            "cryptography is required for logo packaging (pip install cryptography)"
        ) from exc
    padlen = 16 - len(data) % 16
    data = data + bytes([padlen]) * padlen
    enc = Cipher(algorithms.AES(FWU_AES_KEY), modes.CBC(b"\x00" * 16)).encryptor()
    return enc.update(data) + enc.finalize()


def _fwu_header(encrypted_len: int) -> bytes:
    """Return the 160-byte FWI header for a .fwu (CreateFWIHeader)."""
    head = bytearray(
        struct.pack(
            "<IIIIHHIII",
            0,
            FWU_HEADER_LEN,
            FWU_MAGIC,
            0xFFFFFFF7,
            FWU_FILE_TYPE,
            39,
            encrypted_len,
            0,
            0xFFFFFFFF,
        )
        + b"\xff\xff\xff\xff" * FWU_FILLER_U32S
    )
    assert len(head) == FWU_HEADER_LEN, len(head)
    struct.pack_into("<I", head, 0, crc32(bytes(head[4:])))
    return bytes(head)


def build_fwu(asset: LogoAsset, large_screen: bool) -> bytes:
    """Build the NG-family .fwu container (CreateFWUData + WriteFWUFile)."""
    out = bytearray()
    out += _object_record(
        asset.indices,
        OBJECT_LOGO_CUSTOMER,
        PALETTED8,
        asset.width,
        asset.height,
        asset.width,
        0,
        asset.palette,
    )
    blobs = _fixed_blobs()
    for obj in FWU_FIXED_OBJECTS:
        if obj.object_type == OBJECT_ROBOTICA_30 and not large_screen:
            continue
        out += _object_record(
            blobs[obj.name],
            obj.object_type,
            obj.fmt,
            obj.width,
            obj.height,
            obj.stride,
            obj.vertical_offset,
            None,
        )
    out += struct.pack("<I", 0)  # stream trailer

    bin_wrap = bytearray(struct.pack("<IIII", 0, 16 + len(out), 0, 0) + out)
    struct.pack_into("<I", bin_wrap, 0, crc32(bytes(bin_wrap[4:])))
    enc = _aes_encrypt(bytes(bin_wrap))
    return _fwu_header(len(enc)) + enc


def build_tvf(png_path: Path, margin: int = LOGO_MARGIN) -> bytes:
    """Build the AHP-family .tvf container (CreateTvfData)."""
    data = png_path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise LogoError("AHP chargers accept PNG logos only")
    name = png_path.name
    stem = png_path.stem

    manifest = json.dumps(
        {
            "manifest-version": 1,
            "meta": {
                "description": stem,
                "created-by": "alfenctl",
                "created-at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "options": {
                "reboot-scb-after-stage-install": False,
                "wait-for-charging-sessions-to-finish": False,
            },
        },
        separators=(",", ":"),
    )
    resources = json.dumps(
        {"logo": name, "logoMargins": [margin] * 4}, separators=(",", ":")
    )

    def add_text_tar(tar: tarfile.TarFile, arcname: str, content: str) -> None:
        payload = (content + "\n").encode()
        info = tarfile.TarInfo(arcname)
        info.size = len(payload)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(payload))

    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        img_info = tarfile.TarInfo(name)
        img_info.size = len(data)
        img_info.mode = 0o644
        tar.addfile(img_info, io.BytesIO(data))
        add_text_tar(tar, "videoresources.json", resources)
        add_text_tar(tar, "manifest.json", manifest)
    inner_bytes = inner.getvalue()

    gz = io.BytesIO()
    with tarfile.open(fileobj=gz, mode="w:gz", format=tarfile.USTAR_FORMAT) as tar:
        info = tarfile.TarInfo("inner_package.tar")
        info.size = len(inner_bytes)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(inner_bytes))

    header_body = bytearray()
    header_body += struct.pack(
        "<HHIIIIBBBBII", 1, 0, TVF_MAGIC, len(gz.getvalue()), 0, 0, 0, 0, 0, 0, 0, 0
    )
    for text in (b"1", stem.encode()):
        header_body += bytes([len(text)]) + text
    header_body += b"\x00" * 32 + struct.pack("<H", 0)
    header_body += b"\x00" * 256 + struct.pack("<H", 0)
    header_body += b"\x00" * 1024
    header_length = TVF_BASE_HEADER_LENGTH + len(b"1") + len(stem.encode())
    struct.pack_into("<H", header_body, 2, header_length)
    header = bytes(header_body) + struct.pack("<I", crc32(bytes(header_body)))

    result = header + gz.getvalue()
    if len(result) > TVF_MAX_BYTES:
        raise LogoError(
            f"packed logo is {len(result)} bytes; AHP chargers accept at most {TVF_MAX_BYTES}"
        )
    return result


@dataclass(frozen=True)
class DisplayInfo:
    """Whether this charger has a screen, and how big a logo it takes."""

    present: bool = False
    width: int | None = None
    height: int | None = None
    source: str = "none"
    """Where the answer came from: ``reported``, ``model``, or ``none``."""

    @property
    def box(self) -> tuple[int, int]:
        """The logo box, falling back to the app's default for a known screen."""
        if self.width and self.height:
            return self.width, self.height
        return DEFAULT_LOGO_SIZE

    @property
    def large(self) -> bool:
        """Whether this screen is wide enough for the third font object."""
        return self.box[0] > LARGE_SCREEN_WIDTH


def _model_code(model: str | None) -> str:
    """Normalise a model string the way ``ICUDeviceModel.From`` does."""
    text = str(model or "").strip().upper().replace("_", "-").replace(" ", "-")
    if text.startswith("ICU"):
        text = text[3:].lstrip("-")
    return text


def _model_has_a_screen(model: str | None) -> bool:
    """Whether the app would credit this model with a display it never described."""
    code = _model_code(model)
    if code.startswith("EVE-MINI"):
        return True
    return code[:MODEL_CODE_LEN] in OLD_MODELS_WITH_DISPLAY + DUAL_PG_MODELS


def read_display(charger: AlfenCharger, model: str | None = None) -> DisplayInfo:
    """Report whether this charger has a screen, and how big a logo it takes.

    Mirrors ``ICULanDevice.HasDisplay``/``MaxLogoWidth``: a station that
    publishes the display descriptor and a positive logo box has a screen and
    says how big; a handful of models have one without ever describing it;
    anything else has none, and a logo sent to it is a transfer that changes
    nothing.  ``model`` saves a round trip when the caller already knows it.
    """
    try:
        live = charger.fetch_properties_by_ids(
            [PROP_DISPLAY_PRESENT, PROP_LOGO_WIDTH, PROP_LOGO_HEIGHT]
        )
    except Exception:  # a charger that will not answer has not said yes
        live = []
    by_key = {lp.key: lp.value for lp in live}
    width = as_int(by_key.get(PROP_LOGO_WIDTH))
    height = as_int(by_key.get(PROP_LOGO_HEIGHT))
    if PROP_DISPLAY_PRESENT in by_key and width and height and width > 0 and height > 0:
        return DisplayInfo(True, width, height, "reported")
    if model is None:
        model = charger.basic_info().model
    if _model_has_a_screen(model):
        return DisplayInfo(True, *DEFAULT_LOGO_SIZE, "model")
    return DisplayInfo(False, None, None, "none")


def logo_display_limits(charger: AlfenCharger) -> tuple[tuple[int, int], bool]:
    """Read the display box from the charger; ``((w, h), large)``.

    A station with no screen still gets the default box: this only decides
    what an image is scaled to, and refusing to build a package is
    :func:`read_display`'s job and the callers' decision.
    """
    display = read_display(charger)
    return display.box, display.large


def build_package(
    charger: AlfenCharger, image: Path, *, margin: int = LOGO_MARGIN
) -> tuple[bytes, str, tuple[int, int]]:
    """Convert ``image`` into the package this charger takes.

    Returns ``(package bytes, "fwu"|"tvf", display box)``.  Which container
    to build follows the charger's family, so this needs a session even when
    the result is only written to a file.
    """
    box, large = logo_display_limits(charger)
    target = (max(box[0] - 2 * margin, 1), max(box[1] - 2 * margin, 1))

    from alfenctl.firmware import device_family

    info = charger.basic_info()
    if device_family(str(info.model or "")) == "AHP":
        return build_tvf(image, margin), "tvf", box
    return build_fwu(convert_image(image, target), large), "fwu", box


def package_path(destination: Path, kind: str) -> Path:
    """Return where a ``kind`` package should be written, given what was asked for.

    The app's *Create Image Update file* names its output by container, and
    a charger's bootloader dispatches on the extension: a .fwu handed over
    as "splash.png" would simply be refused.
    """
    if destination.suffix.lower() in (f".{kind}", ".fwi"):
        return destination
    return destination.with_suffix(f".{kind}")
