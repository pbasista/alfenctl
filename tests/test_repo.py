"""Tests for the firmware server: listing, compatibility filtering, download."""

from __future__ import annotations

import ftplib
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

import alfenctl.repo as repo_mod
from alfenctl.charger import ChargerInfo
from alfenctl.repo import (
    Candidate,
    RemoteFirmware,
    RepoConfig,
    RepositoryError,
    candidates,
    download,
    list_firmware,
    parse_list_line,
    recommended,
)

NG910 = ChargerInfo(
    object_id="ACE0781464",
    identity="ACE0781464",
    model="NG910-60027",
    family="NG",
    firmware="5.8.1-4123",
    firmware_version=(5, 8, 1),
    sockets=1,
)

# One Unix LIST page as Alfen's server produces it: a mix of NG9xx and AHWP
# images, a .zip release bundle, a subdirectory and a stray file.
LISTING = [
    "-rw-r--r--    1 ftp      ftp       1819296 Jul 31 07:15 NG9xx 7.4.5-4415.fwi",
    "-rw-r--r--    1 ftp      ftp       2022229 Jul 31 07:15 NG9xx 7.6.0-4500.zip",
    "-rw-r--r--    1 ftp      ftp       1750000 Mar 01 2025 NG9xx 6.6.2-4300.fwi",
    "-rw-r--r--    1 ftp      ftp       1700000 Feb 02 2024 NG9xx 5.8.1-4123-A.fwi",
    "-rw-r--r--    1 ftp      ftp        900000 Jan 05 2023 AHWP01_RELEASE_1.1.1.tfw",
    "-rw-r--r--    1 ftp      ftp        500000 Jan 05 2023 ng910v1.2.5-1737.fwi",
    "-rw-r--r--    1 ftp      ftp          1234 Jan 05 2023 readme.txt",
    "drwxr-xr-x    2 ftp      ftp          4096 Jan 05 2023 archive",
]

# The real page served by ftp.alfen.com/Firmware on 2026-08-30, verbatim.
# It is the regression guard for two things the synthetic listing above does
# not exercise: the "AHP_release_FW_..." naming (whose product code is the
# bare "AHP", not the AHP02 the charger reports) and the read-only "r--"
# permission column vsftpd writes.
REAL_LISTING = [
    "-r--r--r-- 1 ftp ftp       78308010 May 02  2025 AHP_release_FW_2.0.0_FULL_cert2025.tfw",
    "-r--r--r-- 1 ftp ftp         358002 May 02  2025 AHP_release_FW_2.0.0_NFC_cert2025.tfw",
    "-r--r--r-- 1 ftp ftp         407409 May 02  2025 AHP_release_FW_2.0.0_SB_cert2025.tfw",
    "-r--r--r-- 1 ftp ftp       77551294 May 02  2025 AHP_release_FW_2.0.0_SCB_cert2025.tfw",
    "-r--r--r-- 1 ftp ftp       45453770 Dec 16  2025 AHP_release_FW_2.3.0_FULL.tfw",
    "-r--r--r-- 1 ftp ftp       45513642 Feb 20  2026 AHP_release_FW_2.4.0_FULL.tfw",
    "-r--r--r-- 1 ftp ftp       45969738 May 13  2026 AHP_release_FW_2.5.0_FULL.tfw",
    "-r--r--r-- 1 ftp ftp         979056 Jul 28 15:10 NG9xx 5.6.1-4414-A.fwi",
    "-r--r--r-- 1 ftp ftp         979056 Jul 28 15:10 NG9xx 5.6.1-4414-B.fwi",
    "-r--r--r-- 1 ftp ftp         978944 Apr 09  2026 NG9xx 6.6.2-4396-BL-upgrade-A.fwi",
    "-r--r--r-- 1 ftp ftp         978944 Apr 09  2026 NG9xx 6.6.2-4396-BL-upgrade-B.fwi",
    "-r--r--r-- 1 ftp ftp        1809424 Sep 17  2025 NG9xx 7.1.6-4345.fwi",
    "-r--r--r-- 1 ftp ftp        1808560 Jul 28 15:10 NG9xx 7.3.0-4411.fwi",
    "-r--r--r-- 1 ftp ftp        1819296 Aug 05 11:59 NG9xx 7.4.5-4415.fwi",
]


def _real_images(now: datetime | None = None) -> list[RemoteFirmware]:
    """Turn REAL_LISTING into the images list_firmware would have produced."""
    now = now or datetime(2026, 8, 30)
    out = []
    for line in REAL_LISTING:
        parsed = parse_list_line(line, now=now)
        assert parsed is not None, line
        out.append(repo_mod._to_remote(*parsed))
    return out


def _charger(model: str, family: str, version: tuple[int, int, int]) -> ChargerInfo:
    return ChargerInfo(
        object_id="x",
        identity=None,
        model=model,
        family=family,
        firmware=".".join(str(p) for p in version),
        firmware_version=version,
        sockets=1,
    )


class FakeFTP:
    """A stand-in for ftplib.FTP that serves LISTING (and files) from memory."""

    files: dict[str, bytes] = {}
    supports_mlsd = False
    fail_on: str | None = None
    connections = 0

    def __init__(self, timeout: float | None = None) -> None:
        self.timeout = timeout
        self.quit_called = False
        type(self).connections += 1

    def connect(self, host: str, port: int) -> None:
        if self.fail_on == "connect":
            raise OSError("connection refused")

    def login(self, user: str, passwd: str) -> None:
        if self.fail_on == "login":
            raise ftplib.error_perm("530 Login incorrect")
        self.user, self.passwd = user, passwd

    def set_pasv(self, value: bool) -> None:
        self.pasv = value

    def mlsd(self, path: str = "", facts: list[str] | None = None):
        if not self.supports_mlsd:
            raise ftplib.error_perm("500 Unknown command")
        yield (
            "NG9xx 7.4.5-4415.fwi",
            {
                "type": "file",
                "size": "1819296",
                "modify": "20260731071500",
            },
        )
        yield "archive", {"type": "dir", "size": "4096", "modify": "20230105000000"}

    # Preset folders, keyed by directory: what LIST returns there.
    preset_listing: dict[str, list[str]] = {}

    def retrlines(self, cmd: str, callback) -> None:
        assert cmd.startswith("LIST")
        directory = cmd[len("LIST ") :].strip()
        if directory in self.preset_listing:
            for line in self.preset_listing[directory]:
                callback(line)
            return
        if directory and directory not in ("", "Firmware"):
            raise ftplib.error_perm("550 No such directory")
        for line in LISTING:
            callback(line)

    def retrbinary(self, cmd: str, callback, blocksize: int = 8192) -> None:
        name = cmd.split(" ", 1)[1]
        data = self.files[name]
        for start in range(0, len(data), blocksize):
            callback(data[start : start + blocksize])

    def quit(self) -> None:
        self.quit_called = True

    def close(self) -> None:
        pass


@pytest.fixture
def fake_ftp(monkeypatch) -> type[FakeFTP]:
    """Install FakeFTP in place of ftplib.FTP, reset between tests."""
    FakeFTP.files = {}
    FakeFTP.preset_listing = {}
    FakeFTP.supports_mlsd = False
    FakeFTP.fail_on = None
    FakeFTP.connections = 0
    monkeypatch.setattr(repo_mod.ftplib, "FTP", FakeFTP)
    return FakeFTP


# --- Listing ------------------------------------------------------------------------------


def test_parse_list_line() -> None:
    name, size, modified = parse_list_line(LISTING[2])
    assert (name, size) == ("NG9xx 6.6.2-4300.fwi", 1750000)
    assert modified == datetime(2025, 3, 1)
    assert parse_list_line(LISTING[-1]) is None  # a directory, not a file
    assert parse_list_line("total 8") is None


def test_parse_list_line_time_form_infers_the_year() -> None:
    line = "-rw-r--r--    1 ftp      ftp       1819296 Jul 31 07:15 fw.fwi"
    _, _, in_past = parse_list_line(line, now=datetime(2026, 8, 29))
    assert in_past == datetime(2026, 7, 31, 7, 15)
    # A "future" date on a year-less listing is really last year's.
    _, _, wrapped = parse_list_line(line, now=datetime(2026, 2, 1))
    assert wrapped == datetime(2025, 7, 31, 7, 15)


def test_list_firmware_uses_list_and_sorts_newest_first(fake_ftp) -> None:
    images = list_firmware(RepoConfig())
    assert [fw.name for fw in images][:3] == [
        "NG9xx 7.6.0-4500.zip",
        "NG9xx 7.4.5-4415.fwi",
        "NG9xx 6.6.2-4300.fwi",
    ]
    assert "archive" not in [fw.name for fw in images]  # directories are skipped
    bundle = images[0]
    assert bundle.is_bundle and bundle.version == (7, 6, 0)


def test_list_firmware_prefers_mlsd(fake_ftp) -> None:
    fake_ftp.supports_mlsd = True
    images = list_firmware(RepoConfig())
    assert [fw.name for fw in images] == ["NG9xx 7.4.5-4415.fwi"]
    assert images[0].modified == datetime(2026, 7, 31, 7, 15)
    assert images[0].size == 1819296


def test_list_firmware_reports_an_unreachable_server(fake_ftp) -> None:
    fake_ftp.fail_on = "connect"
    with pytest.raises(RepositoryError, match="cannot reach ftp.alfen.com"):
        list_firmware(RepoConfig())


def test_list_firmware_reports_bad_credentials(fake_ftp) -> None:
    fake_ftp.fail_on = "login"
    with pytest.raises(RepositoryError, match="530"):
        list_firmware(RepoConfig())


def test_repo_config_defaults_to_alfens_own_server() -> None:
    cfg = RepoConfig()
    assert cfg.site == "ftp.alfen.com"
    assert cfg.username == "installer"  # the app's shared installer account
    assert cfg.location == "ftp.alfen.com/Firmware"


# --- Compatibility ------------------------------------------------------------------------


def _cands(info: ChargerInfo = NG910, **kw) -> list[Candidate]:
    return candidates(list_firmware(RepoConfig()), info, **kw)


def test_candidates_keep_only_this_charger_s_images(fake_ftp) -> None:
    names = [c.fw.name for c in _cands()]
    assert names == [
        "NG9xx 7.6.0-4500.zip",
        "NG9xx 7.4.5-4415.fwi",
        "NG9xx 6.6.2-4300.fwi",
        "NG9xx 5.8.1-4123-A.fwi",
        "ng910v1.2.5-1737.fwi",  # an NG910-only image, and this is an NG910
    ]
    # Dropped: the AHWP image (wrong family) and readme.txt (not an image).
    assert "AHWP01_RELEASE_1.1.1.tfw" not in names
    assert "readme.txt" not in names


def test_candidates_drop_another_model_s_image_unless_all(fake_ftp) -> None:
    ng920 = ChargerInfo(
        object_id="x",
        identity=None,
        model="NG920-61001",
        family="NG",
        firmware="5.8.1-4123",
        firmware_version=(5, 8, 1),
        sockets=2,
    )
    # The NG910-only image is not offered for an NG920 (the app, which filters
    # on the extension alone, would have offered it)...
    assert "ng910v1.2.5-1737.fwi" not in [c.fw.name for c in _cands(ng920)]
    # ...but --all lists it, flagged with what it is built for.
    shown = {c.fw.name: c for c in _cands(ng920, include_all=True)}
    other = shown["ng910v1.2.5-1737.fwi"]
    assert not other.matches_model
    assert any("built for NG910" in w for w in other.warnings)
    # A .tfw is for the other charger family: --all does not resurrect it.
    assert "AHWP01_RELEASE_1.1.1.tfw" not in shown


def test_candidates_annotate_what_the_change_means(fake_ftp) -> None:
    by_name = {c.fw.name: c for c in _cands()}
    assert by_name["NG9xx 5.8.1-4123-A.fwi"].notes == ["currently installed"]
    assert by_name["NG9xx 6.6.2-4300.fwi"].notes == ["upgrade"]
    # 5.8.1 -> 7.4.5 must go via 6.6.2 first (the app's red warning label).
    assert any("6.6.2" in w for w in by_name["NG9xx 7.4.5-4415.fwi"].warnings), by_name[
        "NG9xx 7.4.5-4415.fwi"
    ].warnings


def test_candidates_warn_about_the_5_0_password_barrier(fake_ftp) -> None:
    old = ChargerInfo(
        object_id="x",
        identity=None,
        model="NG910-60027",
        family="NG",
        firmware="4.9.0-3200",
        firmware_version=(4, 9, 0),
        sockets=1,
    )
    by_name = {c.fw.name: c for c in _cands(old)}
    stone = by_name["NG9xx 6.6.2-4300.fwi"]
    assert any("unique password" in w for w in stone.warnings)
    # Crossing 5.0 only needs --new-password, so it does not rule the image
    # out: 6.6.2 is still what a 4.9.0 charger should be taken to next.
    assert not stone.blocked
    assert recommended(_cands(old)).fw.name == "NG9xx 6.6.2-4300.fwi"


def test_candidates_for_an_ahp_charger(fake_ftp) -> None:
    ahp = ChargerInfo(
        object_id="x",
        identity=None,
        model="AHWP01-52654",
        family="AHP",
        firmware="1.1.0",
        firmware_version=(1, 1, 0),
        sockets=1,
    )
    assert [c.fw.name for c in _cands(ahp)] == ["AHWP01_RELEASE_1.1.1.tfw"]


# --- Against the real server listing --------------------------------------------------------


def test_every_real_listing_line_parses() -> None:
    images = _real_images()
    assert len(images) == len(REAL_LISTING)
    assert images[7].name == "NG9xx 5.6.1-4414-A.fwi"
    assert images[7].modified == datetime(2026, 7, 28, 15, 10)
    assert images[6].modified == datetime(2026, 5, 13)
    # The variant suffixes Alfen actually uses stay out of the version.
    stone = next(i for i in images if "BL-upgrade-A" in i.name)
    assert stone.version == (6, 6, 2)
    assert stone.release.build == 4396
    assert stone.release.variant == "BL-upgrade-A"


def test_real_ahp_images_are_offered_to_an_ahp_charger() -> None:
    ahp = _charger("AHP02-63142", "AHP", (2, 3, 0))
    cands = candidates(_real_images(), ahp)
    # All seven .tfw files, newest release first, and no NG9xx image.
    assert [c.fw.name for c in cands][:3] == [
        "AHP_release_FW_2.5.0_FULL.tfw",
        "AHP_release_FW_2.4.0_FULL.tfw",
        "AHP_release_FW_2.3.0_FULL.tfw",
    ]
    assert len(cands) == 7
    assert all(c.matches_model for c in cands)
    assert recommended(cands).fw.name == "AHP_release_FW_2.5.0_FULL.tfw"


def test_real_ng_images_are_ordered_by_version_not_date() -> None:
    # 5.6.1-4414 has a higher build number and a newer mtime than 7.3.0-4411,
    # so only version-first ordering puts 7.x on top.
    cands = candidates(_real_images(), NG910)
    assert [c.fw.name for c in cands] == [
        "NG9xx 7.4.5-4415.fwi",
        "NG9xx 7.3.0-4411.fwi",
        "NG9xx 7.1.6-4345.fwi",
        "NG9xx 6.6.2-4396-BL-upgrade-B.fwi",
        "NG9xx 6.6.2-4396-BL-upgrade-A.fwi",
        "NG9xx 5.6.1-4414-B.fwi",
        "NG9xx 5.6.1-4414-A.fwi",
    ]
    # A 5.8.1 charger is steered to the 6.6.2 stepping stone, not to 7.4.5.
    assert recommended(cands).fw.name == "NG9xx 6.6.2-4396-BL-upgrade-B.fwi"


def test_a_retired_product_code_still_lists_the_family() -> None:
    # Nothing on the server is named for an AHWP01 any more. Rather than
    # telling the owner of one that no firmware exists (the app would have
    # listed every .tfw), show the family flagged -- and recommend none.
    ahwp = _charger("AHWP01-52654", "AHP", (1, 1, 1))
    cands = candidates(_real_images(), ahwp)
    assert len(cands) == 7
    assert not any(c.matches_model for c in cands)
    assert all(c.blocked for c in cands)
    assert all(any("built for AHP" in w for w in c.warnings) for c in cands)
    assert recommended(cands) is None


def test_recommended_is_the_newest_valid_next_step(fake_ftp) -> None:
    cands = _cands()
    # 7.6.0 and 7.4.5 both need the 6.6.2 stepping stone first, so 6.6.2 wins.
    assert recommended(cands).fw.name == "NG9xx 6.6.2-4300.fwi"
    blocked = {c.fw.name: c.blocked for c in cands}
    assert blocked["NG9xx 7.6.0-4500.zip"] and blocked["NG9xx 7.4.5-4415.fwi"]
    assert not blocked["NG9xx 6.6.2-4300.fwi"]


def test_recommended_is_none_when_nothing_is_newer(fake_ftp) -> None:
    current = ChargerInfo(
        object_id="x",
        identity=None,
        model="NG910-60027",
        family="NG",
        firmware="9.9.9",
        firmware_version=(9, 9, 9),
        sockets=1,
    )
    assert recommended(_cands(current)) is None


# --- Download -----------------------------------------------------------------------------


def _remote(name: str, data: bytes) -> RemoteFirmware:
    FakeFTP.files[f"Firmware/{name}"] = data
    return repo_mod._to_remote(name, len(data), datetime(2026, 7, 31, 7, 15))


def test_download_writes_into_the_cache(fake_ftp, tmp_path: Path, capsys) -> None:
    fw = _remote("NG9xx 7.4.5-4415.fwi", b"image-bytes" * 100)
    path = download(fw, "NG", cache_dir=tmp_path)
    assert path == tmp_path / "NG9xx 7.4.5-4415.fwi"
    assert path.read_bytes() == b"image-bytes" * 100
    assert int(path.stat().st_mtime) == int(fw.modified.timestamp())
    assert "Downloading" in capsys.readouterr().out


def test_download_reuses_a_cached_copy(fake_ftp, tmp_path: Path, capsys) -> None:
    fw = _remote("NG9xx 7.4.5-4415.fwi", b"x" * 64)
    download(fw, "NG", cache_dir=tmp_path)
    fake_ftp.connections = 0
    download(fw, "NG", cache_dir=tmp_path)
    assert fake_ftp.connections == 0  # no second transfer
    assert "cached copy" in capsys.readouterr().out


def test_download_refetches_a_truncated_cached_copy(fake_ftp, tmp_path: Path) -> None:
    fw = _remote("NG9xx 7.4.5-4415.fwi", b"y" * 64)
    (tmp_path / fw.name).write_bytes(b"partial")
    assert download(fw, "NG", cache_dir=tmp_path).read_bytes() == b"y" * 64


def test_download_unpacks_a_release_bundle(fake_ftp, tmp_path: Path) -> None:
    bundle = tmp_path / "src.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("NG9xx 7.6.0-4500.fwi", b"the-image")
        zf.writestr("NG9xx 7.6.0-4500-cert.pem", b"cert")
        zf.writestr("NG9xx 7.6.0-4500-info.txt", b"Valid until 2027-02-04")
    fw = _remote("NG9xx 7.6.0-4500.zip", bundle.read_bytes())
    cache = tmp_path / "cache"
    path = download(fw, "NG", cache_dir=cache)
    assert path == cache / "NG9xx 7.6.0-4500.fwi"
    assert path.read_bytes() == b"the-image"


def test_download_rejects_a_bundle_without_an_image(fake_ftp, tmp_path: Path) -> None:
    bundle = tmp_path / "src.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("notes.txt", b"nothing to install here")
    fw = _remote("NG9xx 7.6.0-4500.zip", bundle.read_bytes())
    with pytest.raises(RepositoryError, match="no .fwi"):
        download(fw, "NG", cache_dir=tmp_path / "cache")


def test_download_leaves_no_partial_file_behind(
    fake_ftp, tmp_path: Path, monkeypatch
) -> None:
    fw = _remote("NG9xx 7.4.5-4415.fwi", b"z" * 4096)

    def die(self, cmd, callback, blocksize=8192):  # patched onto the class
        callback(b"z" * 512)  # a few bytes land, then the transfer dies
        raise ftplib.error_temp("426 Transfer aborted")

    monkeypatch.setattr(fake_ftp, "retrbinary", die)
    with pytest.raises(RepositoryError):
        download(fw, "NG", cache_dir=tmp_path)
    assert not (tmp_path / fw.name).exists()


# --- Presets ---------------------------------------------------------------------------


PRESET_LISTING = {
    "TCPPresets": [
        "-rw-r--r--    1 ftp      ftp          812 Jul 31 07:15 ABB B23 TCP.xml",
        "-rw-r--r--    1 ftp      ftp          640 Jul 31 07:15 readme.txt",
        "-rw-r--r--    1 ftp      ftp          420 Jul 31 07:15 Socomec E23.json",
    ],
    "RTUPresets": [
        "-rw-r--r--    1 ftp      ftp          700 Mar 01 2025 Eastron SDM630.xml",
    ],
    "BackofficePresets": [],
}

PRESET_XML = (
    "<Settings><XMLVersion>1.0</XMLVersion><Properties>"
    '<Property Id="2062_00" Value="16.0" />'
    "</Properties></Settings>"
)


def test_list_presets_walks_every_folder(fake_ftp) -> None:
    fake_ftp.preset_listing = PRESET_LISTING
    presets = repo_mod.list_presets()
    assert [p.label for p in presets] == [
        "Eastron SDM630",
        "ABB B23 TCP",
        "Socomec E23",
    ]
    assert {p.kind for p in presets} == {
        "Modbus RTU meter settings",
        "Modbus TCP meter settings",
        "Modbus TCP meter map",
    }


def test_list_presets_separates_maps_from_settings(fake_ftp) -> None:
    """The same folders hold register maps (JSON) and settings (XML)."""
    fake_ftp.preset_listing = PRESET_LISTING
    by_label = {p.label: p for p in repo_mod.list_presets()}
    assert by_label["Socomec E23"].is_meter_map
    assert not by_label["ABB B23 TCP"].is_meter_map


def test_list_presets_ignores_other_files(fake_ftp) -> None:
    fake_ftp.preset_listing = PRESET_LISTING
    assert all(not p.name.endswith(".txt") for p in repo_mod.list_presets())


def test_list_presets_skips_a_folder_the_server_lacks(fake_ftp) -> None:
    """Not every server publishes all three folders."""
    fake_ftp.preset_listing = {"TCPPresets": PRESET_LISTING["TCPPresets"]}
    assert [p.label for p in repo_mod.list_presets()] == [
        "ABB B23 TCP",
        "Socomec E23",
    ]


def test_fetch_preset_returns_the_xml(fake_ftp) -> None:
    fake_ftp.preset_listing = PRESET_LISTING
    fake_ftp.files = {"TCPPresets/ABB B23 TCP.xml": PRESET_XML.encode()}
    preset = next(p for p in repo_mod.list_presets() if p.label == "ABB B23 TCP")
    assert repo_mod.fetch_preset(preset) == PRESET_XML


# --- backoffice presets: blobs, not documents -------------------------------------------------

BACKOFFICE_LISTING = {
    "BackofficePresets": [
        "-rw-r--r--    1 ftp      ftp         1280 Jul 31 07:15 4th-Dimension-A.fwi",
        "-rw-r--r--    1 ftp      ftp         1280 Jul 31 07:15 4th-Dimension-B.fwi",
        "-rw-r--r--    1 ftp      ftp         1152 Jul 31 07:15 Abel&Co-A.fwi",
        "-rw-r--r--    1 ftp      ftp         1152 Jul 31 07:15 Abel&Co-B.fwi",
        "-rw-r--r--    1 ftp      ftp         1216 Jul 31 07:15 Unkeyed.fwi",
        "-rw-r--r--    1 ftp      ftp          640 Jul 31 07:15 readme.txt",
    ]
}


def test_backoffice_presets_are_listed_and_named_without_their_key(fake_ftp) -> None:
    fake_ftp.preset_listing = BACKOFFICE_LISTING
    presets = repo_mod.list_presets()
    assert [p.name for p in presets] == [
        "4th-Dimension-A.fwi",
        "4th-Dimension-B.fwi",
        "Abel&Co-A.fwi",
        "Abel&Co-B.fwi",
        "Unkeyed.fwi",
    ]
    assert {p.label for p in presets} == {"4th-Dimension", "Abel&Co", "Unkeyed"}
    assert [p.variant for p in presets] == ["A", "B", "A", "B", None]
    assert all(p.is_backoffice and not p.is_meter_map for p in presets)
    assert presets[0].kind == "backoffice preset"


def test_the_firmware_decides_which_key_is_downloaded(fake_ftp) -> None:
    fake_ftp.preset_listing = BACKOFFICE_LISTING
    both = [p for p in repo_mod.list_presets() if p.label == "Abel&Co"]
    assert repo_mod.pick_backoffice_variant(both, (7, 4, 5)).variant == "B"
    assert repo_mod.pick_backoffice_variant(both, (4, 12, 0)).variant == "B"
    assert repo_mod.pick_backoffice_variant(both, (4, 11, 9)).variant == "A"
    assert repo_mod.pick_backoffice_variant(both, None).variant == "A"


def test_an_unkeyed_preset_is_taken_whatever_the_firmware(fake_ftp) -> None:
    fake_ftp.preset_listing = BACKOFFICE_LISTING
    only = [p for p in repo_mod.list_presets() if p.label == "Unkeyed"]
    assert repo_mod.pick_backoffice_variant(only, (7, 4, 5)).name == "Unkeyed.fwi"


def test_a_backoffice_preset_is_fetched_as_bytes(fake_ftp) -> None:
    fake_ftp.preset_listing = BACKOFFICE_LISTING
    blob = bytes(range(256))
    fake_ftp.files = {"BackofficePresets/Unkeyed.fwi": blob}
    (preset,) = [p for p in repo_mod.list_presets() if p.label == "Unkeyed"]
    assert repo_mod.fetch_preset_bytes(preset) == blob
