"""Tests for ``alfenctl config`` -- the settings file, without a charger."""

from __future__ import annotations

from pathlib import Path

import pytest

from alfenctl import cli
from alfenctl.config import EXAMPLE_CONFIG, default_config_dir, load_config


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    """Point every default-path lookup at a directory of our own."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "alfen" / "alfen.toml"


# --- Where the file lives --------------------------------------------------------------------


def test_xdg_config_home_wins_everywhere(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("sys.platform", "win32")
    assert default_config_dir() == tmp_path / "alfen"


def test_windows_uses_appdata(monkeypatch) -> None:
    """~/.config is not where a Windows program keeps its settings."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\ann\AppData\Roaming")
    assert default_config_dir().parts[-1] == "alfen"
    assert "AppData" in str(default_config_dir())


def test_everything_else_uses_dot_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert default_config_dir() == tmp_path / ".config" / "alfen"


# --- The starter file ------------------------------------------------------------------------


def _written(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "alfen.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_starter_file_changes_nothing_as_shipped(tmp_path: Path) -> None:
    """Every line is commented out, so a fresh file cannot break a command."""
    config = load_config(_written(tmp_path, EXAMPLE_CONFIG))
    assert config.username is None and not config.stations


def test_uncommenting_the_starter_file_yields_what_it_promises(tmp_path: Path) -> None:
    """The example is only worth shipping if its lines actually parse."""
    settings = [
        line.removeprefix("# ")
        for line in EXAMPLE_CONFIG.splitlines()
        if line.startswith("# [") or (line.startswith("# ") and "=" in line)
    ]
    live = "\n".join(settings)
    config = load_config(_written(tmp_path, live))  # raises on a bad key or type
    assert config.username == "admin"
    assert config.station("garage").host == "192.168.11.42"
    assert config.station("old").http is True
    assert config.firmware.site == "ftp.example.com"


# --- The commands ----------------------------------------------------------------------------


def test_config_path_prints_the_default_location(home: Path, capsys) -> None:
    assert cli.main(["config", "path"]) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == str(home)


def test_config_init_writes_a_file_and_the_directory_under_it(
    home: Path, capsys
) -> None:
    assert cli.main(["config", "init"]) == cli.EXIT_OK
    assert home.read_text(encoding="utf-8") == EXAMPLE_CONFIG
    assert str(home) in capsys.readouterr().out


def test_config_init_asks_before_replacing_one(home: Path, monkeypatch) -> None:
    home.parent.mkdir(parents=True)
    home.write_text("host = '10.0.0.9'\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    assert cli.main(["config", "init"]) == cli.EXIT_ERROR
    assert "10.0.0.9" in home.read_text(encoding="utf-8")

    assert cli.main(["config", "init", "-y"]) == cli.EXIT_OK
    assert "10.0.0.9" not in home.read_text(encoding="utf-8")


def test_config_show_says_where_to_start_when_there_is_no_file(
    home: Path, capsys
) -> None:
    assert cli.main(["config"]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert str(home) in err
    assert "alfenctl config init" in err


def test_config_show_lists_the_stations_without_the_passwords(
    home: Path, capsys
) -> None:
    home.parent.mkdir(parents=True)
    home.write_text(
        'password = "top-secret"\n'
        "[stations.garage]\n"
        'host = "192.168.11.42"\n'
        'password = "also-secret"\n',
        encoding="utf-8",
    )
    assert cli.main(["config", "show"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "garage" in out and "192.168.11.42" in out
    assert "secret" not in out


def test_config_takes_no_charger(home: Path, capsys, monkeypatch) -> None:
    """It must work before there is a charger to talk to at all."""

    def no(*a, **k):
        raise AssertionError("opened a connection")

    monkeypatch.setattr("alfenctl.cli.target.AlfenCharger", no)
    assert cli.main(["config", "path"]) == cli.EXIT_OK
