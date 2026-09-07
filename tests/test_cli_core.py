"""Tests for the CLI's spine: finding a charger, the config file and default actions."""

from __future__ import annotations

import json

import pytest

from conftest import (
    STATION,
    FakeCharger,
    patch_charger,
    patch_discover,
)

from alfenctl import cli
from alfenctl.discovery import Station
from alfenctl.eds import load_catalog


def test_no_command_prints_help(capsys) -> None:
    assert cli.main([]) == cli.EXIT_ERROR
    assert "usage:" in capsys.readouterr().out


def test_list_mode_prints_stations(capsys, monkeypatch) -> None:
    patch_discover(monkeypatch, lambda duration: [STATION])
    assert cli.main(["list"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "1 charging station" in out
    assert "ace0781464" in out
    assert "https" in out


def test_list_mode_reports_no_chargers(capsys, monkeypatch) -> None:
    patch_discover(monkeypatch, lambda duration: [])
    assert cli.main(["list"]) == cli.EXIT_ERROR
    assert "No chargers found" in capsys.readouterr().err


def test_station_not_found(capsys, monkeypatch) -> None:
    patch_discover(monkeypatch, lambda duration: [])
    assert cli.main(["info", "--station", "NOPE"]) == cli.EXIT_ERROR
    assert "error: no station selected" in capsys.readouterr().err


def test_host_mode_skips_discovery(capsys, monkeypatch, fake_charger) -> None:
    def boom(duration: float) -> list[Station]:
        raise AssertionError("discovery must not run with --host")

    patch_discover(monkeypatch, boom)
    assert cli.main(["info", "--host", "192.168.11.42"]) == cli.EXIT_OK


def test_config_file_supplies_host_and_credentials(
    capsys, tmp_path, monkeypatch, fake_charger
) -> None:

    cfg = tmp_path / "alfen.toml"
    cfg.write_text(
        '[stations.garage]\nhost = "1.2.3.4"\nusername = "admin"\npassword = "s3cret"\n'
    )
    seen: dict[str, object] = {}

    def fake_charger_ctor(station, username, password, **kwargs):
        seen["station"], seen["u"], seen["p"] = station, username, password
        return fake_charger

    patch_charger(monkeypatch, fake_charger_ctor)
    assert (
        cli.main(["info", "--station", "garage", "--config", str(cfg)]) == cli.EXIT_OK
    )
    assert seen["station"].ip == "1.2.3.4"
    assert seen["u"] == "admin"
    assert seen["p"] == "s3cret"


def test_flag_overrides_config(capsys, tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "alfen.toml"
    cfg.write_text('[stations.garage]\nhost = "1.2.3.4"\nusername = "cfg-user"\n')
    seen: dict[str, object] = {}

    def fake_charger_ctor(station, username, password, **kwargs):
        seen["station"], seen["u"] = station, username
        fc = FakeCharger()
        return fc

    patch_charger(monkeypatch, fake_charger_ctor)
    assert (
        cli.main(
            ["info", "--station", "garage", "--config", str(cfg), "-u", "flag-user"]
        )
        == cli.EXIT_OK
    )
    assert seen["u"] == "flag-user"


def test_catalog_loads() -> None:
    catalog = load_catalog()
    assert len(catalog) > 600
    assert catalog.get((0x2050, 0)) is not None


def test_config_port_yields_to_an_explicit_port(tmp_path, monkeypatch) -> None:

    cfg = tmp_path / "alfen.toml"
    cfg.write_text('[stations.garage]\nhost = "1.2.3.4"\nport = 4443\n')
    seen: dict[str, object] = {}

    def fake_charger_ctor(station, username, password, **kwargs):
        seen["station"] = station
        return FakeCharger()

    patch_charger(monkeypatch, fake_charger_ctor)
    base = ["info", "--station", "garage", "--config", str(cfg)]
    assert cli.main(base) == cli.EXIT_OK
    assert seen["station"].port == 4443  # the configured port
    for typed in (["--port", "8443"], ["--port=8443"]):
        assert cli.main(base + typed) == cli.EXIT_OK
        assert seen["station"].port == 8443  # the one on the command line


def test_a_station_overrides_the_top_level_credentials(tmp_path, monkeypatch) -> None:
    """The top-level keys are defaults; a station table is the specific answer."""
    cfg = tmp_path / "alfen.toml"
    cfg.write_text(
        'username = "everyone"\npassword = "shared"\n'
        '[stations.garage]\nhost = "1.2.3.4"\npassword = "just-mine"\n'
    )
    seen: dict[str, object] = {}

    def fake_charger_ctor(station, username, password, **kwargs):
        seen["u"], seen["p"] = username, password
        return FakeCharger()

    patch_charger(monkeypatch, fake_charger_ctor)
    assert (
        cli.main(["info", "--station", "garage", "--config", str(cfg)]) == cli.EXIT_OK
    )
    assert seen["u"] == "everyone"  # not set for the station, so the default
    assert seen["p"] == "just-mine"


def test_options_are_read_from_sys_argv(tmp_path, monkeypatch) -> None:
    """With no argv, main() takes the real command line, options and all."""
    import sys

    cfg = tmp_path / "alfen.toml"
    cfg.write_text('[stations.garage]\nhost = "1.2.3.4"\nport = 4443\n')
    seen: dict[str, object] = {}

    def fake_charger_ctor(station, username, password, **kwargs):
        seen["station"] = station
        return FakeCharger()

    patch_charger(monkeypatch, fake_charger_ctor)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alfenctl",
            "info",
            "--station",
            "garage",
            "--config",
            str(cfg),
            "--port",
            "8443",
        ],
    )
    assert cli.main() == cli.EXIT_OK
    assert seen["station"].port == 8443


# --- Default actions ----------------------------------------------------------------------


def test_insert_default_action_fills_in_a_missing_action() -> None:
    assert cli.insert_default_action(["tags"]) == ["tags", "list"]
    assert cli.insert_default_action(["whitelist"]) == ["whitelist", "list"]
    assert cli.insert_default_action(["scn"]) == ["scn", "status"]
    assert cli.insert_default_action(["license"]) == ["license", "show"]
    assert cli.insert_default_action(["charging-profiles"]) == [
        "charging-profiles",
        "list",
    ]


def test_insert_default_action_passes_options_to_the_default() -> None:
    assert cli.insert_default_action(["scn", "--peers", "--host", "1.2.3.4"]) == [
        "scn",
        "status",
        "--peers",
        "--host",
        "1.2.3.4",
    ]


def test_insert_default_action_leaves_everything_else_alone() -> None:
    # An explicit action, a mistyped one (argparse reports the bad choice),
    # a help request, a command without a default, and no command at all.
    for argv in (
        ["tags", "list", "--json"],
        ["tags", "bogus"],
        ["tags", "-h"],
        ["scn", "--help"],
        ["password"],
        ["props", "tags"],
        [],
    ):
        assert cli.insert_default_action(list(argv)) == argv


def test_tags_without_an_action_lists(fake_charger, capsys) -> None:
    assert cli.main(["tags", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "04A1B2C3" in out and "2 tag(s)." in out


def test_tags_without_an_action_keeps_its_options(fake_charger, capsys) -> None:
    assert cli.main(["tags", "--json", "--host", "1.2.3.4"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [t["tag"] for t in doc] == ["04A1B2C3", "04FFEE11"]


def test_scn_without_an_action_shows_the_membership(fake_charger, capsys) -> None:
    assert cli.main(["scn", "--host", "1.2.3.4"]) == 0
    assert "not a member" in capsys.readouterr().out


def test_license_without_an_action_shows(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += [
        {"id": "21A1_0", "value": "0011.2233.4455.6677.8899.AABB"},
    ]
    assert cli.main(["license", "--host", "1.2.3.4"]) == 0
    assert "0011.2233.4455.6677.8899.AABB" in capsys.readouterr().out


def test_charging_profiles_without_an_action_lists(fake_charger, capsys) -> None:
    assert cli.main(["charging-profiles", "--host", "1.2.3.4"]) == 0
    assert "No charging profiles" in capsys.readouterr().out


def test_password_still_requires_an_action(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["password"])
    assert exc.value.code == 2
    assert "required: ACTION" in capsys.readouterr().err
