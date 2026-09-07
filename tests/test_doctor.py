"""``alfenctl doctor``: what it finds, and what it does when it cannot look.

The checks themselves are tested where they live -- this is about the pass
over them: that a station with nothing wrong says so, that a station out of
service exits non-zero, and that a check which cannot run is named rather
than quietly counting as a pass.
"""

from __future__ import annotations

import json

import pytest

from alfenctl import cli, doctor


def _props(fake_charger, entries: list[dict]) -> None:
    fake_charger.docs["/api/prop"]["properties"] += entries


def test_a_station_with_nothing_wrong_says_so(fake_charger, capsys) -> None:
    assert cli.main(["doctor", "--host", "1.2.3.4"]) == 0
    assert "Nothing to report" in capsys.readouterr().out


def test_a_station_out_of_service_is_an_error(fake_charger, capsys) -> None:
    _props(fake_charger, [{"id": "205F_0", "access": 2, "type": 7, "value": 1}])
    assert cli.main(["doctor", "--host", "1.2.3.4"]) == 1
    out = capsys.readouterr().out
    assert "the whole station is out of service" in out
    assert "alfenctl socket enable" in out


def test_a_socket_out_of_service_is_a_warning_not_an_error(
    fake_charger, capsys
) -> None:
    _props(
        fake_charger,
        [
            {"id": "205F_0", "access": 2, "type": 7, "value": 2},
            {"id": "2501_4", "access": 1, "type": 5, "value": 1},
        ],
    )
    assert cli.main(["doctor", "--host", "1.2.3.4"]) == 0
    assert "socket 1 is out of service" in capsys.readouterr().out


def test_a_device_state_error_is_reported_with_its_code(fake_charger, capsys) -> None:
    _props(
        fake_charger,
        [
            {"id": "2501_4", "access": 1, "type": 5, "value": 1},
            {"id": "3190_1", "access": 1, "type": 5, "value": 16},
            {"id": "3190_2", "access": 1, "type": 6, "value": 401},
        ],
    )
    cli.main(["doctor", "--host", "1.2.3.4"])
    assert "401" in capsys.readouterr().out


def test_the_factory_identity_is_flagged(fake_charger, capsys) -> None:
    import dataclasses

    from conftest import INFO

    stock = dataclasses.replace(INFO, identity=doctor.UNCOMMISSIONED_IDENTITY)
    fake_charger.basic_info = lambda: stock
    assert cli.main(["doctor", "--host", "1.2.3.4"]) == 0
    assert "factory default" in capsys.readouterr().out


def test_a_socket_limit_above_the_stations_is_flagged(fake_charger, capsys) -> None:
    _props(
        fake_charger,
        [
            {"id": "205E_0", "access": 1, "type": 5, "value": 1},
            {"id": "2129_0", "access": 2, "type": 8, "value": 32.0},
        ],
    )
    # The fixture's station maximum (2062_0) is 25 A.
    assert cli.main(["doctor", "--host", "1.2.3.4"]) == 0
    assert "limits:" in capsys.readouterr().out


def test_direct_start_left_on_is_a_note(fake_charger, capsys) -> None:
    _props(fake_charger, [{"id": "3278_1", "access": 2, "type": 5, "value": 1}])
    assert cli.main(["doctor", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "ignore the installed charging profile" in out
    assert "alfenctl direct-start off --socket 1" in out


def test_a_check_that_cannot_run_is_named(fake_charger, capsys, monkeypatch) -> None:
    def boom(charger):
        raise RuntimeError("this charger has no tilt sensor")

    monkeypatch.setattr("alfenctl.tilt.read", boom)
    assert cli.main(["doctor", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Could not check:" in out
    assert "tilt: this charger has no tilt sensor" in out


def test_one_broken_check_does_not_stop_the_others(
    fake_charger, capsys, monkeypatch
) -> None:
    def boom(charger):
        raise RuntimeError("nope")

    monkeypatch.setattr("alfenctl.clock.read", boom)
    _props(fake_charger, [{"id": "205F_0", "access": 2, "type": 7, "value": 1}])
    assert cli.main(["doctor", "--host", "1.2.3.4"]) == 1
    out = capsys.readouterr().out
    assert "out of service" in out and "clock: nope" in out


def test_json_carries_the_same_findings(fake_charger, capsys) -> None:
    _props(fake_charger, [{"id": "205F_0", "access": 2, "type": 7, "value": 1}])
    assert cli.main(["doctor", "--json", "--host", "1.2.3.4"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["worst"] == "error"
    assert doc["findings"][0]["area"] == "sockets"


@pytest.mark.parametrize(
    ("findings", "worst"),
    [
        ([], None),
        ([(doctor.NOTE, "a")], doctor.NOTE),
        ([(doctor.NOTE, "a"), (doctor.ERROR, "b")], doctor.ERROR),
        ([(doctor.WARNING, "a"), (doctor.NOTE, "b")], doctor.WARNING),
    ],
)
def test_worst_is_the_highest_severity_present(findings, worst) -> None:
    report = doctor.Report(
        findings=[doctor.Finding(sev, area, area) for sev, area in findings]
    )
    assert report.worst == worst
