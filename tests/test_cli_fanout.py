"""Running one read over several stations: --station a,b and --station all."""

from __future__ import annotations

import json

import pytest
from conftest import FakeCharger, patch_charger, patch_discover

from alfenctl import cli

TWO_STATIONS = (
    '[stations.garage]\nhost = "1.2.3.4"\n\n[stations.drive]\nhost = "5.6.7.8"\n'
)


@pytest.fixture
def two_stations(tmp_path, monkeypatch):
    """A config naming two stations, and a charger for each, recorded in order."""
    cfg = tmp_path / "alfen.toml"
    cfg.write_text(TWO_STATIONS)
    opened: list[str] = []

    def ctor(station, username, password, **kwargs):
        opened.append(station.ip)
        return FakeCharger()

    patch_charger(monkeypatch, ctor)
    patch_discover(monkeypatch, lambda duration: [])
    return cfg, opened


def test_one_station_is_untouched_by_any_of_this(fake_charger, capsys) -> None:
    # No heading, no wrapper: exactly what it printed before there was a
    # fan-out at all.
    assert cli.main(["status", "--host", "1.2.3.4"]) == cli.EXIT_OK
    assert "===" not in capsys.readouterr().out


def test_a_list_of_stations_reads_each_in_turn(two_stations, capsys) -> None:
    cfg, opened = two_stations
    argv = ["status", "--station", "garage,drive", "--config", str(cfg)]
    assert cli.main(argv) == cli.EXIT_OK
    assert opened == ["1.2.3.4", "5.6.7.8"]  # in the order they were named
    out = capsys.readouterr().out
    assert "=== garage " in out
    assert "=== drive " in out


def test_all_means_the_stations_the_config_file_names(two_stations, capsys) -> None:
    cfg, opened = two_stations
    assert cli.main(["status", "--station", "all", "--config", str(cfg)]) == cli.EXIT_OK
    assert opened == ["1.2.3.4", "5.6.7.8"]


def test_all_does_not_mean_whatever_mdns_can_see(tmp_path, monkeypatch, capsys) -> None:
    # A browse answers with whatever is on the network, some of which may be
    # the neighbours'.  `all` is what the configuration file names.
    from alfenctl.discovery import Station

    cfg = tmp_path / "alfen.toml"
    cfg.write_text("")
    patch_discover(
        monkeypatch,
        lambda duration: [Station(ip="9.9.9.9", port=443, hostname="ACE-NOTMINE")],
    )
    patch_charger(monkeypatch, lambda *a, **k: FakeCharger())
    assert (
        cli.main(["status", "--station", "all", "--config", str(cfg)]) == cli.EXIT_ERROR
    )
    err = capsys.readouterr().err
    assert "no [stations.<name>] tables" in err


def test_json_over_several_stations_is_one_document(two_stations, capsys) -> None:
    cfg, _opened = two_stations
    argv = ["props", "--json", "--station", "garage,drive", "--config", str(cfg)]
    assert cli.main(argv) == cli.EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    # One object keyed by station, not two documents in a row.
    assert sorted(doc) == ["drive", "garage"]
    assert doc["garage"] and doc["garage"] == doc["drive"]


def test_a_station_that_does_not_answer_costs_only_its_own_section(
    tmp_path, monkeypatch, capsys
) -> None:
    import httpx

    cfg = tmp_path / "alfen.toml"
    cfg.write_text(TWO_STATIONS)
    read: list[str] = []

    def ctor(station, username, password, **kwargs):
        fc = FakeCharger()
        if station.ip == "1.2.3.4":
            fc.login_error = httpx.ConnectError("refused")
        else:
            read.append(station.ip)
        return fc

    patch_charger(monkeypatch, ctor)
    argv = ["status", "--station", "garage,drive", "--config", str(cfg)]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert read == ["5.6.7.8"]  # the other one was still read
    assert "garage: cannot reach the charger" in capsys.readouterr().err


def test_a_command_that_writes_refuses_a_list(two_stations, capsys) -> None:
    cfg, opened = two_stations
    argv = [
        "current",
        "set",
        "16",
        "--station",
        "garage,drive",
        "--config",
        str(cfg),
    ]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert opened == []  # nothing was even opened
    assert "one station at a time" in capsys.readouterr().err


def test_the_reading_action_of_that_same_command_does_not(two_stations) -> None:
    cfg, opened = two_stations
    argv = ["current", "show", "--station", "garage,drive", "--config", str(cfg)]
    assert cli.main(argv) == cli.EXIT_OK
    assert opened == ["1.2.3.4", "5.6.7.8"]


def test_a_host_and_a_list_of_stations_is_an_error(two_stations, capsys) -> None:
    cfg, opened = two_stations
    argv = [
        "status",
        "--station",
        "garage,drive",
        "--host",
        "9.9.9.9",
        "--config",
        str(cfg),
    ]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert opened == []
    assert "--host is one charger's address" in capsys.readouterr().err


def test_a_stray_comma_is_still_one_station(two_stations) -> None:
    cfg, opened = two_stations
    assert cli.main(["status", "--station", "garage,", "--config", str(cfg)]) == 0
    assert opened == ["1.2.3.4"]


def test_watching_several_stations_at_once_is_refused(two_stations, capsys) -> None:
    # The watch loop would be inside the fan-out rather than around it: the
    # first station would redraw forever and the second would never be read.
    cfg, opened = two_stations
    argv = ["status", "--watch", "2", "--station", "garage,drive", "--config", str(cfg)]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert opened == []
    assert "--watch follows one station" in capsys.readouterr().err
