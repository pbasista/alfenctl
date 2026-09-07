"""Tests for ``alfenctl firmware`` and ``alfenctl logo``.

These are about what the user sees and what the exit code says; the
sequence they drive is tested in test_upgrade.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from conftest import INFO, make_fwi

from alfenctl import cli
from alfenctl.cli.commands.firmware import choose_firmware, print_candidates
from alfenctl.repo import RemoteFirmware, RepositoryError, candidates
from alfenctl.upgrade import InstallFailed


def _remote(name: str, size: int = 1_800_000) -> RemoteFirmware:
    from alfenctl.firmware import parse_release_name

    return RemoteFirmware(
        name=name,
        size=size,
        modified=datetime(2026, 7, 31, 7, 15),
        release=parse_release_name(name),
        is_bundle=name.endswith(".zip"),
    )


PUBLISHED = [
    _remote("NG9xx 7.6.0-4500.fwi"),
    _remote("NG9xx 7.4.5-4415.fwi"),
    _remote("NG9xx 7.2.0-4300.fwi"),
]


def _publish(monkeypatch, firmware: list[RemoteFirmware]) -> None:
    """Make the firmware server offer exactly ``firmware``."""
    monkeypatch.setattr(
        "alfenctl.cli.commands.firmware.list_firmware", lambda config: firmware
    )


@pytest.fixture
def offered(monkeypatch, tmp_path: Path):
    """Serve PUBLISHED as the server's listing; downloads land in tmp_path."""
    _publish(monkeypatch, PUBLISHED)

    def fake_download(fw, family, *, config=None, cache_dir=None, on_progress=None):
        path = (cache_dir or tmp_path) / fw.name
        path.write_bytes(make_fwi())
        return path

    monkeypatch.setattr("alfenctl.cli.commands.firmware.download", fake_download)
    return PUBLISHED


@pytest.fixture
def installed(monkeypatch):
    """Let the install run without waiting for a charger to reboot."""
    monkeypatch.setattr("alfenctl.upgrade.poll_until_done", lambda charger, **kw: None)


# --- The parser ------------------------------------------------------------------------------


def test_firmware_file_is_optional() -> None:
    """No file means "ask the server what it has"; a file still works."""
    args = cli.build_parser().parse_args(["firmware"])
    assert args.file is None
    assert args.command == "firmware"
    assert cli.build_parser().parse_args(["firmware", "fw.fwi"]).file == Path("fw.fwi")


# --- Listing what the server offers ----------------------------------------------------------


def test_firmware_list_shows_what_the_server_offers(
    capsys, monkeypatch, fake_charger, tmp_path
) -> None:
    _publish(
        monkeypatch,
        [_remote("NG9xx 7.6.0-4500.fwi"), _remote("AHWP01_RELEASE_1.1.1.tfw")],
    )
    rc = cli.main(
        ["firmware", "--list", "--host", "192.168.11.42", "--cache-dir", str(tmp_path)]
    )
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "NG9xx 7.6.0-4500.fwi" in out
    assert "AHWP01" not in out  # the other charger family
    assert str(tmp_path) in out  # where a download would land


def test_firmware_list_reports_an_empty_shelf(
    capsys, monkeypatch, fake_charger
) -> None:
    _publish(monkeypatch, [_remote("AHWP01_RELEASE_1.1.1.tfw")])
    rc = cli.main(["firmware", "--list", "--host", "192.168.11.42"])
    assert rc == cli.EXIT_NO_FIRMWARE
    err = capsys.readouterr().err
    assert "no firmware for NG910-60027" in err
    assert "--all" in err


def test_firmware_list_reports_an_unreachable_server(
    capsys, monkeypatch, fake_charger
) -> None:
    def boom(config):
        raise RepositoryError("cannot reach ftp.alfen.com: timed out")

    monkeypatch.setattr("alfenctl.cli.commands.firmware.list_firmware", boom)
    rc = cli.main(["firmware", "--list", "--host", "192.168.11.42"])
    assert rc == cli.EXIT_NO_FIRMWARE
    assert "cannot reach ftp.alfen.com" in capsys.readouterr().err


def test_print_candidates_shows_every_column(capsys) -> None:
    print_candidates(candidates(PUBLISHED, INFO), INFO, "ftp.alfen.com/Firmware")
    out = capsys.readouterr().out
    assert "NG910-60027" in out and "ftp.alfen.com/Firmware" in out
    assert "7.6.0-4500" in out  # version
    assert "2026-07-31" in out  # release date
    assert "1.8 MB" in out  # size


# --- Picking a release ------------------------------------------------------------------------


def test_choose_firmware_lists_and_downloads_the_pick(offered, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    path = choose_firmware(INFO, cache_dir=None)
    assert path.name == "NG9xx 7.4.5-4415.fwi"
    out = capsys.readouterr().out
    assert "NG9xx 7.6.0-4500.fwi" in out  # the whole compatible list is shown
    assert "currently installed" in out  # ...annotated against this charger
    assert "upgrade" in out


def test_choose_firmware_default_is_the_newest_clean_upgrade(offered, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")  # accept the default
    assert choose_firmware(INFO).name == "NG9xx 7.6.0-4500.fwi"


def test_choose_firmware_reprompts_on_a_bad_answer(offered, monkeypatch, capsys):
    replies = iter(["nonsense", "9", "3"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))
    assert choose_firmware(INFO).name == "NG9xx 7.2.0-4300.fwi"
    assert "one of the numbers" in capsys.readouterr().out


def test_choose_firmware_can_be_cancelled(offered, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "q")
    assert choose_firmware(INFO) is None


def test_choose_firmware_stops_at_end_of_input(offered, monkeypatch) -> None:
    """An unattended run must not loop forever on a question nobody answers."""

    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert choose_firmware(INFO) is None


def test_choose_firmware_yes_takes_the_recommendation(offered, capsys) -> None:
    assert choose_firmware(INFO, yes=True).name == "NG9xx 7.6.0-4500.fwi"
    assert "--yes" in capsys.readouterr().out


def test_choose_firmware_yes_refuses_without_a_recommendation(offered) -> None:
    # Already on the newest release: there is no clear next step, so --yes
    # must not silently reinstall or downgrade -- it stops and says so.
    from dataclasses import replace

    current = replace(INFO, firmware="7.6.0-4500", firmware_version=(7, 6, 0))
    with pytest.raises(RepositoryError, match="no clear next release"):
        choose_firmware(current, yes=True)


def test_choose_firmware_raises_when_nothing_fits(monkeypatch) -> None:
    _publish(monkeypatch, [])
    with pytest.raises(RepositoryError, match="no firmware for NG910-60027"):
        choose_firmware(INFO)


# --- The upgrade itself -------------------------------------------------------------------


def test_firmware_upgrade_reports_the_whole_run(
    fake_charger, installed, capsys, tmp_path
) -> None:
    image = tmp_path / "NG9xx 7.4.5-4415.fwi"
    image.write_bytes(make_fwi())

    rc = cli.main(["firmware", str(image), "-y", "--host", "1.2.3.4"])

    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "=> compatible" in out
    assert "Firmware updated successfully." in out
    assert "firmware: 7.4.5-4415 -> 7.4.5-4415" in out
    assert fake_charger.uploads  # the image really went out


def test_firmware_upgrade_stops_at_an_incompatible_image(
    fake_charger, capsys, tmp_path
) -> None:
    image = tmp_path / "image.tfw"  # .tfw is for AHP-family chargers only
    image.write_bytes(make_fwi())

    rc = cli.main(["firmware", str(image), "-y", "--host", "1.2.3.4"])

    assert rc == cli.EXIT_INCOMPATIBLE
    assert "not compatible" in capsys.readouterr().err
    assert not fake_charger.uploads


def test_firmware_upgrade_stops_when_one_is_already_running(
    fake_charger, capsys, tmp_path
) -> None:
    fake_charger.upload_in_progress = True
    image = tmp_path / "NG9xx 7.4.5-4415.fwi"
    image.write_bytes(make_fwi())

    rc = cli.main(["firmware", str(image), "-y", "--host", "1.2.3.4"])

    assert rc == cli.EXIT_UPLOAD_IN_PROGRESS
    assert "already in progress" in capsys.readouterr().err
    assert not fake_charger.uploads


def test_firmware_upgrade_reports_an_install_that_never_finished(
    fake_charger, monkeypatch, capsys, tmp_path
) -> None:
    def boom(charger, **kw):
        raise InstallFailed("the charger did not come back after the firmware upload")

    monkeypatch.setattr("alfenctl.upgrade.poll_until_done", boom)
    image = tmp_path / "NG9xx 7.4.5-4415.fwi"
    image.write_bytes(make_fwi())

    rc = cli.main(["firmware", str(image), "-y", "--host", "1.2.3.4"])

    assert rc == cli.EXIT_UPDATE_FAILED
    assert "did not come back" in capsys.readouterr().err


def test_firmware_upgrade_asks_before_it_uploads(
    fake_charger, installed, monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    image = tmp_path / "NG9xx 7.4.5-4415.fwi"
    image.write_bytes(make_fwi())

    assert cli.main(["firmware", str(image), "--host", "1.2.3.4"]) == cli.EXIT_ERROR
    assert not fake_charger.uploads
    assert "Cancelled." in capsys.readouterr().err


def test_firmware_upgrade_picks_from_the_server_when_given_no_file(
    fake_charger, offered, installed, monkeypatch, capsys
) -> None:
    # Pick release 2 from the list, then confirm the upgrade itself: the
    # compatibility report sits between the two answers.
    replies = iter(["2", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))

    assert cli.main(["firmware", "--host", "1.2.3.4"]) == cli.EXIT_OK
    assert fake_charger.uploads
    assert "NG9xx 7.4.5-4415.fwi" in capsys.readouterr().out


def test_firmware_upgrade_says_how_to_carry_on_without_a_server(
    fake_charger, monkeypatch, capsys
) -> None:
    def boom(config):
        raise RepositoryError("cannot reach ftp.alfen.com: timed out")

    monkeypatch.setattr("alfenctl.cli.commands.firmware.list_firmware", boom)

    assert cli.main(["firmware", "--host", "1.2.3.4"]) == cli.EXIT_NO_FIRMWARE
    assert "cannot reach ftp.alfen.com" in capsys.readouterr().err
    assert not fake_charger.uploads


def test_firmware_upgrade_cancelled_at_the_picker_does_nothing(
    fake_charger, offered, monkeypatch, capsys
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "q")

    assert cli.main(["firmware", "--host", "1.2.3.4"]) == cli.EXIT_ERROR
    assert "Cancelled." in capsys.readouterr().err
    assert not fake_charger.uploads


# --- The logo -------------------------------------------------------------------------------


@pytest.fixture
def packaged(monkeypatch):
    """Return a factory that fixes what build_package produces."""

    def _fix(kind: str = "fwu", box: tuple[int, int] = (320, 160)) -> None:
        monkeypatch.setattr(
            "alfenctl.logo.build_package",
            lambda charger, image, margin=0: (b"PKG", kind, box),
        )

    return _fix


def test_logo_save_writes_the_package_without_uploading(
    fake_charger, packaged, capsys, tmp_path
) -> None:
    packaged()
    out_file = tmp_path / "logo.fwu"
    argv = ["logo", "logo.png", "--save", str(out_file), "--host", "1.2.3.4"]
    assert cli.main(argv) == cli.EXIT_OK
    assert out_file.read_bytes() == b"PKG"
    assert not fake_charger.uploads
    assert "Wrote 3 bytes" in capsys.readouterr().out


def test_logo_save_names_the_file_by_package_kind(
    fake_charger, packaged, tmp_path
) -> None:
    packaged(kind="tvf", box=(800, 350))
    argv = ["logo", "logo.png", "--save", str(tmp_path / "splash"), "--host", "1.2.3.4"]
    assert cli.main(argv) == cli.EXIT_OK
    assert (tmp_path / "splash.tvf").read_bytes() == b"PKG"


@pytest.fixture
def screenless(fake_charger):
    """Take the display descriptor away: a station with no screen at all."""
    props = fake_charger.docs["/api/prop"]["properties"]
    fake_charger.docs["/api/prop"]["properties"] = [
        p for p in props if not p["id"].startswith("3260_")
    ]
    return fake_charger


def test_logo_upload_refuses_when_there_is_no_display(
    screenless, packaged, capsys
) -> None:
    """The vendor app greys its own upload button out here."""
    assert cli.main(["logo", "logo.png", "-y", "--host", "1.2.3.4"]) == cli.EXIT_ERROR
    assert "no display" in capsys.readouterr().err
    assert not screenless.uploads


def test_logo_upload_to_a_screenless_station_goes_out_with_force(
    screenless, packaged, capsys
) -> None:
    packaged()
    rc = cli.main(["logo", "logo.png", "-y", "--force", "--host", "1.2.3.4"])
    assert rc == cli.EXIT_OK
    assert screenless.uploads == [b"PKG"]
    assert "no display" in capsys.readouterr().err  # said, and done anyway


def test_logo_upload_refuses_without_the_licence(
    fake_charger, packaged, capsys
) -> None:
    packaged()
    assert cli.main(["logo", "logo.png", "-y", "--host", "1.2.3.4"]) == cli.EXIT_ERROR
    assert "not licensed" in capsys.readouterr().err
    assert not fake_charger.uploads


def test_logo_upload_goes_out_with_force(fake_charger, packaged, capsys) -> None:
    packaged()
    rc = cli.main(["logo", "logo.png", "-y", "--force", "--host", "1.2.3.4"])
    assert rc == cli.EXIT_OK
    assert fake_charger.uploads == [b"PKG"]
    assert "Logo uploaded." in capsys.readouterr().out


def test_logo_upload_asks_first(fake_charger, packaged, monkeypatch, capsys) -> None:
    packaged()
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    rc = cli.main(["logo", "logo.png", "--force", "--host", "1.2.3.4"])
    assert rc == cli.EXIT_ERROR
    assert not fake_charger.uploads
