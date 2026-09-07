"""Tests for firmware image parsing and compatibility rules."""

from __future__ import annotations

from pathlib import Path

from conftest import make_fwi

from alfenctl.firmware import (
    FirmwareFile,
    allowed_extensions,
    check_compatibility,
    device_family,
    needs_stepping_stone,
    parse_fw_version,
    parse_release_name,
    product_code,
    product_matches_model,
    strip_firmware_suffix,
)


def test_parse_fw_version() -> None:
    assert parse_fw_version("7.4.5-4415") == (7, 4, 5)
    assert parse_fw_version("5.6.1") == (5, 6, 1)
    assert parse_fw_version("X.6.1") == (99, 6, 1)  # wildcard component, as the app
    assert parse_fw_version("unknown") is None
    assert parse_fw_version("1.2") is None
    assert parse_fw_version("a.b.c") is None


def test_device_family() -> None:
    assert device_family("NG910-60027") == "NG"
    assert device_family("Eve Single S") == "NG"
    assert device_family("AHP-1P-32A") == "AHP"
    assert device_family("AHWP22-3P") == "AHP"
    assert device_family("") == "NG"


def test_allowed_extensions() -> None:
    assert allowed_extensions("NG") == (".fwi", ".fwu")
    assert allowed_extensions("AHP") == (".tfw", ".tcf")


def _load(tmp_path: Path, name: str, data: bytes | None = None) -> FirmwareFile:
    p = tmp_path / name
    p.write_bytes(make_fwi() if data is None else data)
    return FirmwareFile.load(p)


def test_firmware_file_valid_container(tmp_path: Path) -> None:
    fw = _load(tmp_path, "NG9xx 7.4.5-4415.fwi")
    assert fw.version == (7, 4, 5)
    assert fw.is_alfen_container is True
    assert fw.header_ok is True


def test_firmware_file_corrupt_container(tmp_path: Path) -> None:
    fw = _load(tmp_path, "NG9xx 7.4.5-4415.fwi", make_fwi(corrupt=True))
    assert fw.is_alfen_container is True
    assert fw.header_ok is False


def test_firmware_file_not_a_container(tmp_path: Path) -> None:
    fw = _load(tmp_path, "NG9xx 7.4.5-4415.fwi", b"not an alfen header" * 20)
    assert fw.is_alfen_container is False
    assert fw.header_ok is None


def test_firmware_file_without_version_in_name(tmp_path: Path) -> None:
    assert _load(tmp_path, "image.fwi").version is None


def test_check_compatible(tmp_path: Path) -> None:
    res = check_compatibility("NG", (7, 3, 0), _load(tmp_path, "NG9xx 7.4.5-4415.fwi"))
    assert res.ok
    assert not res.errors and not res.warnings
    assert res.notes == ["charger 7.3.0 -> file 7.4.5"]


def test_check_wrong_extension(tmp_path: Path) -> None:
    res = check_compatibility("NG", (7, 3, 0), _load(tmp_path, "pkg.tfw"))
    assert not res.ok
    assert any("'.tfw'" in e for e in res.errors)


def test_check_downgrade_warns(tmp_path: Path) -> None:
    res = check_compatibility("NG", (7, 4, 5), _load(tmp_path, "NG9xx 7.3.0-4411.fwi"))
    assert res.ok
    assert any("downgrade" in w for w in res.warnings)


def test_check_5_0_boundary_warns(tmp_path: Path) -> None:
    res = check_compatibility("NG", (4, 9, 9), _load(tmp_path, "NG9xx 5.0.0-4000.fwi"))
    assert res.ok
    assert any("5.0" in w for w in res.warnings)


def test_check_corrupt_header_blocks(tmp_path: Path) -> None:
    fw = _load(tmp_path, "NG9xx 7.4.5-4415.fwi", make_fwi(corrupt=True))
    res = check_compatibility("NG", (7, 4, 5), fw)
    assert not res.ok
    assert any("CRC32" in e for e in res.errors)


def test_check_no_version_in_filename_warns(tmp_path: Path) -> None:
    res = check_compatibility("NG", (7, 4, 5), _load(tmp_path, "image.fwi"))
    assert res.ok
    assert any("version" in w for w in res.warnings)


def test_strip_firmware_suffix_keeps_dotted_versions() -> None:
    assert strip_firmware_suffix("NG9xx 7.4.5-4415.fwi") == "NG9xx 7.4.5-4415"
    assert strip_firmware_suffix("NG9xx 7.4.5-4415.ZIP") == "NG9xx 7.4.5-4415"
    # Path.suffix would eat "-3398-A" here; only known extensions come off.
    assert strip_firmware_suffix("NG9xx 4.14.0-3398-A") == "NG9xx 4.14.0-3398-A"


def test_parse_release_name() -> None:
    ng = parse_release_name("NG9xx 7.4.5-4415.fwi")
    assert (ng.product, ng.version, ng.build, ng.label) == (
        "NG9xx",
        (7, 4, 5),
        4415,
        "7.4.5-4415",
    )
    variant = parse_release_name("NG9xx 5.8.1-4123-A.fwi")
    assert (variant.version, variant.build, variant.variant) == ((5, 8, 1), 4123, "A")
    ahp = parse_release_name("AHWP01_RELEASE_1.1.1-NFC.tfw")
    assert (ahp.product, ahp.version, ahp.build, ahp.variant) == (
        "AHWP01_RELEASE",
        (1, 1, 1),
        None,
        "NFC",
    )
    # The app's own regex needs "_" or " " before the version and reads no
    # version out of these two older names; ours does.
    assert parse_release_name("ng910v1.2.5-1737.fwi").label == "1.2.5-1737"
    assert parse_release_name("ng910 1.2.8 - 2164.fwi").label == "1.2.8-2164"
    unversioned = parse_release_name("readme.txt")
    assert unversioned.version is None and unversioned.label == ""


def test_product_code_and_model_match() -> None:
    assert product_code("AHWP01_RELEASE") == "AHWP01"
    assert product_code("NG910-60027") == "NG910"
    assert product_code("") == ""
    # "x" is Alfen's digit wildcard: NG9xx covers every NG9xx model...
    assert product_matches_model("NG9xx", "NG910-60027")
    assert product_matches_model("NG9xx", "NG920-61001")
    # ...but a product code without wildcards only covers its own model,
    # and AHWP01 images are not for an AHP02 even though both are .tfw.
    assert not product_matches_model("ng910", "NG920-61001")
    assert not product_matches_model("AHWP01", "AHP02-63142")
    assert product_matches_model("AHWP01", "AHWP01-52654")
    assert not product_matches_model("NG9xx", "")


def test_product_match_covers_alfens_real_ahp_naming() -> None:
    # Alfen publishes the Eve/AHP line as "AHP_release_FW_2.5.0_FULL.tfw",
    # whose product code is the bare "AHP" -- yet the chargers it serves call
    # themselves AHP02/AHPDC. Matching the release code as a prefix keeps
    # that pairing (an exact match would have hidden every real AHP image).
    product = parse_release_name("AHP_release_FW_2.5.0_FULL.tfw").product
    assert product_code(product) == "AHP"
    assert product_matches_model(product, "AHP02-63142")
    assert product_matches_model(product, "AHPDC-70001")
    # ...without swallowing the neighbouring AHWP01 line.
    assert not product_matches_model(product, "AHWP01-52654")
    # A prefix must still not merge two distinct NG models.
    assert not product_matches_model("NG910", "NG920-61001")


def test_needs_stepping_stone() -> None:
    assert needs_stepping_stone("NG", (5, 8, 1), (7, 4, 5))
    assert not needs_stepping_stone("NG", (6, 6, 2), (7, 4, 5))  # already at 6.6
    assert not needs_stepping_stone("NG", (5, 8, 1), (6, 6, 2))  # the stone itself
    assert not needs_stepping_stone("AHP", (1, 1, 0), (7, 0, 0))
    assert not needs_stepping_stone("NG", None, (7, 4, 5))


def test_check_stepping_stone_warns(tmp_path: Path) -> None:
    res = check_compatibility("NG", (5, 8, 1), _load(tmp_path, "NG9xx 7.4.5-4415.fwi"))
    assert res.ok  # a warning, not a refusal: the user may know better
    assert any("6.6.2" in w for w in res.warnings)
