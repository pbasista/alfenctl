"""Tests for the logo containers (FWU for NG, TVF for AHP) and conversion."""

from __future__ import annotations

import io
import json
import struct
import tarfile
import zlib
from pathlib import Path

import pytest

from alfenctl import logo
from alfenctl.logo import (
    FWU_AES_KEY,
    FWU_FIXED_OBJECTS,
    MAX_COLORS,
    LogoAsset,
    build_fwu,
    build_tvf,
    convert_image,
    crc32,
)

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

RECORD = "<BBHHHIIBBHHhII"  # 32-byte object record header


def _decrypt(fwu: bytes) -> bytes:
    dec = Cipher(algorithms.AES(FWU_AES_KEY), modes.CBC(b"\x00" * 16)).decryptor()
    bw = dec.update(fwu[160:]) + dec.finalize()
    return bw[: len(bw) - bw[-1]]  # strip PKCS7 padding


def _asset(w: int = 8, h: int = 6) -> LogoAsset:
    # Full-size palette like convert_image ships: MAX_COLORS entries (the
    # app's Wu quantizer + ConvertImage always pad to maxColors).
    palette = bytes([255, 0, 0, 0, 0, 255]) + bytes(MAX_COLORS * 3 - 6)
    indices = bytes((i + j) % 2 for i in range(w) for j in range(h))
    return LogoAsset(width=w, height=h, indices=indices, palette=palette)


def _walk(fwu: bytes) -> list[tuple]:
    """Walk the object stream, returning (fields, raw_data) per record."""
    plain = _decrypt(fwu)
    stream = plain[16:]
    out = []
    at = 0
    while at < len(stream) and stream[at : at + 4] != b"\x00\x00\x00\x00":
        fields = struct.unpack_from(RECORD, stream, at)
        ver, otype, w, h, stride, olen, clen, fmt, ncm1, paloff, doff = fields[:11]
        blob = stream[at + doff : at + doff + clen]
        raw = zlib.decompress(blob[2:], -15)  # skip the 78 9C prefix
        out.append((fields, raw, blob))
        at += olen  # olen == total record size (C# pads to a 4-byte multiple)
    assert at + 4 == len(stream)  # trailer exactly at the end
    return out


def test_fwu_header_shape_and_crc() -> None:
    fwu = build_fwu(_asset(), large_screen=False)
    assert struct.unpack_from("<I", fwu, 4)[0] == 160  # header length field
    assert struct.unpack_from("<I", fwu, 8)[0] == 0xA1FE0013  # .fwu magic
    # (ushort)41473 == 0xA201: the parser dispatches on this file-type
    # word; the charger logs "Unexpected UpdateFirmware file type" for
    # anything else (a 0xA1E1 mistranscription got HTTP 400).
    assert struct.unpack_from("<H", fwu, 16)[0] == 0xA201
    assert struct.unpack_from("<H", fwu, 18)[0] == 39  # header version
    assert struct.unpack_from("<I", fwu, 20)[0] == len(fwu) - 160
    assert struct.unpack_from("<I", fwu, 0)[0] == crc32(fwu[4:160])
    assert fwu[28:32] == b"\xff\xff\xff\xff"
    assert fwu[32:160] == b"\xff" * 128  # 32 filler u32s
    plain = _decrypt(fwu)
    assert struct.unpack_from("<I", plain, 0)[0] == crc32(plain[4:])
    # C# stores 16 + stream length, which equals the whole plaintext.
    assert struct.unpack_from("<I", plain, 4)[0] == len(plain)


def test_fwu_object_stream_contents() -> None:
    asset = _asset()
    records = _walk(build_fwu(asset, large_screen=False))
    types = [f[1] for f, _, _ in records]
    assert types == [0, 1, 2, 3, 4, 5, 6]
    # Customer logo record: ver 1, PALETTED8, exact geometry, palette on disk.
    fields, raw, blob = records[0]
    ver, otype, w, h, stride, olen, clen, fmt, ncm1, paloff, doff, voff = fields[:12]
    assert (ver, otype, fmt, voff) == (1, 0, 16, 0)
    assert (w, h, stride) == (asset.width, asset.height, asset.width)
    assert ncm1 == len(asset.palette) // 3 - 1
    assert paloff == 32 and doff == 32 + len(asset.palette)
    assert raw == asset.indices
    assert crc32(raw) == fields[12] and crc32(blob) == fields[13]
    assert olen == 32 + len(asset.palette) + clen + (
        -(32 + len(asset.palette) + clen) % 4
    )
    # Fixed objects: ver 1, no palette, declared geometry from the app's table.
    for (fields, raw, _), obj in zip(records[1:], FWU_FIXED_OBJECTS[:6]):
        assert fields[2:5] == (obj.width, obj.height, obj.stride)
        assert fields[11:12] == (obj.vertical_offset,)
        assert len(raw) == obj.blob_bytes
        assert fields[9] == 0  # nColorsM1: no palette on fixed objects


def test_fwu_large_screen_includes_font_30() -> None:
    records = _walk(build_fwu(_asset(), large_screen=True))
    assert [f[1] for f, _, _ in records] == [0, 1, 2, 3, 4, 5, 6, 8]


def test_fwu_fixed_blobs_are_verbatim() -> None:
    """What we ship must still be byte-identical to the app's ICUObjects.cs.

    Through ``tools/extract_assets.py``, which is the documented way to
    rebuild the file: this checks the tool and the file at once, so neither
    can drift while the other looks fine.
    """
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    source = root.parent / "work/src/ACEFWUCreator/ICUFWUCreator/ICUObjects.cs"
    if not source.is_file():  # vendor sources are not distributed
        pytest.skip("decompiled ICUObjects.cs not available")

    spec = importlib.util.spec_from_file_location(
        "extract_assets", root / "tools" / "extract_assets.py"
    )
    extract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract)

    shipped = (root / "src" / "alfenctl" / "logo_blobs.bin").read_bytes()
    assert extract.build_blobs(source) == shipped


def test_convert_image_cover_scaling_and_palette() -> None:
    from PIL import Image

    img = Image.new("RGB", (600, 200))
    for x in range(0, 600, 6):
        for y in range(0, 200, 6):
            img.paste(
                (x % 256, (x * 3) % 256, (y * 5) % 256),
                (x, y, min(x + 6, 600), min(y + 6, 200)),
            )
    p = Path("/tmp/_alfen_logo_t.png")
    img.save(p)
    asset = convert_image(p, (304, 144))
    # Cover rule: scale = max(600/304, 200/144) = 600/304 -> 304x~101.
    assert asset.width == 304
    assert asset.height == 101
    assert len(asset.indices) == 304 * 101
    assert len(asset.palette) % 3 == 0
    assert len(asset.palette) // 3 <= 128


def test_convert_image_rejects_unreadable(tmp_path: Path) -> None:
    from alfenctl.logo import LogoError

    bad = tmp_path / "not-an-image.png"
    bad.write_bytes(b"\x00" * 64)
    with pytest.raises(LogoError):
        convert_image(bad, (304, 144))


def test_tvf_roundtrip(tmp_path: Path) -> None:
    from PIL import Image

    png = tmp_path / "my logo.png"
    Image.new("RGB", (100, 50), (9, 9, 9)).save(png)
    tvf = build_tvf(png)
    hdr_len = struct.unpack_from("<H", tvf, 2)[0]
    assert struct.unpack_from("<I", tvf, 4)[0] == 3102571221
    assert struct.unpack_from("<I", tvf, 8)[0] == len(tvf) - hdr_len - 4
    # Header CRC = last 4 bytes of the header region.
    assert struct.unpack_from("<I", tvf, hdr_len)[0] == crc32(tvf[:hdr_len])
    with tarfile.open(fileobj=io.BytesIO(tvf[hdr_len + 4 :]), mode="r:gz") as tar:
        m = tar.next()
        assert m.name == "inner_package.tar"
        with tarfile.open(fileobj=tar.extractfile(m), mode="r:") as inner:
            names = [mm.name for mm in inner.getmembers()]
            assert names == ["my logo.png", "videoresources.json", "manifest.json"]
            vr = json.loads(inner.extractfile("videoresources.json").read())
            assert vr == {"logo": "my logo.png", "logoMargins": [8, 8, 8, 8]}
            man = json.loads(inner.extractfile("manifest.json").read())
            assert man["manifest-version"] == 1
            assert man["meta"]["description"] == "my logo"
            assert man["options"] == {
                "reboot-scb-after-stage-install": False,
                "wait-for-charging-sessions-to-finish": False,
            }
            assert inner.extractfile("my logo.png").read() == png.read_bytes()


def test_tvf_rejects_non_png(tmp_path: Path) -> None:
    from PIL import Image

    jpg = tmp_path / "x.jpg"
    Image.new("RGB", (10, 10)).save(jpg)
    from alfenctl.logo import LogoError

    with pytest.raises(LogoError):
        build_tvf(jpg)


# --- who has a screen at all ---------------------------------------------------------------


class _Station:
    """A charger that answers for exactly the properties it was given."""

    def __init__(self, model: str, values: dict[tuple[int, int], int] | None = None):
        self.model = model
        self.values = values or {}
        self.identified = 0

    def fetch_properties_by_ids(self, keys):
        from alfenctl.charger import LiveProperty

        return [
            LiveProperty(id=f"{p:X}_{s:X}", key=(p, s), value=self.values[(p, s)])
            for p, s in keys
            if (p, s) in self.values
        ]

    def basic_info(self):
        from alfenctl.charger import ChargerInfo

        self.identified += 1
        return ChargerInfo(
            object_id="ACE0000001",
            identity="bench",
            model=self.model,
            family="NG",
            firmware="7.4.5-4415",
            firmware_version=(7, 4, 5),
            sockets=1,
        )


SCREEN = {
    logo.PROP_DISPLAY_PRESENT: 320,
    logo.PROP_LOGO_WIDTH: 320,
    logo.PROP_LOGO_HEIGHT: 165,
}


def test_a_station_that_describes_its_screen_has_one() -> None:
    display = logo.read_display(_Station("NG910-60027", SCREEN))
    assert (display.present, display.width, display.height) == (True, 320, 165)
    assert display.source == "reported"
    assert display.large is False  # 320 is the boundary, not past it


def test_a_wide_screen_is_a_large_one() -> None:
    wide = dict(SCREEN) | {logo.PROP_LOGO_WIDTH: 800, logo.PROP_LOGO_HEIGHT: 350}
    assert logo.read_display(_Station("NG920-62001", wide)).large is True


def test_a_station_that_describes_no_screen_has_none() -> None:
    station = _Station("NG910-60027")
    display = logo.read_display(station)
    assert display.present is False
    assert display.source == "none"
    assert display.box == logo.DEFAULT_LOGO_SIZE  # what an image is still built for


@pytest.mark.parametrize(
    "model", ["NG910-60014", "NG910-60034", "Eve Mini", "ICU Eve Mini", "NG920-62003"]
)
def test_the_models_with_a_screen_they_never_describe(model: str) -> None:
    """ICULanDevice.IsOldModelWithDisplay and IsDualPG, in the app's own words."""
    display = logo.read_display(_Station(model))
    assert display.present is True
    assert display.source == "model"
    assert display.box == logo.DEFAULT_LOGO_SIZE


def test_a_half_answered_descriptor_is_not_a_screen() -> None:
    """A logo box of zero is what a station without one reports."""
    half = {
        logo.PROP_DISPLAY_PRESENT: 0,
        logo.PROP_LOGO_WIDTH: 0,
        logo.PROP_LOGO_HEIGHT: 0,
    }
    assert logo.read_display(_Station("NG910-60027", half)).present is False


def test_the_model_is_not_read_twice_when_the_caller_knows_it() -> None:
    station = _Station("NG910-60027")
    logo.read_display(station, "NG910-60027")
    assert station.identified == 0
