"""Tests for ``alfenctl info``, ``status``, ``wifi`` and the smart-meter test."""

from __future__ import annotations

import json

import pytest
from datetime import datetime, timezone


from alfenctl import cli
from alfenctl import network as net
from alfenctl.cli.commands import network as netcmd


def test_info_mode_prints_details(capsys, fake_charger) -> None:
    assert cli.main(["info", "--host", "192.168.11.42"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "NG910-60027" in out
    assert "7.4.5-4415" in out


def test_status_reports_the_live_state(fake_charger, capsys) -> None:
    assert cli.main(["status", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "ACE0781464 (NG910-60027)" in out
    assert "Socket 1     available" in out
    assert "Mode 3: A (no vehicle)" in out
    assert "42.6 C" in out


def test_status_json(fake_charger, capsys) -> None:
    assert cli.main(["status", "--json", "--host", "1.2.3.4"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["sockets"][0]["state"] == "available"
    assert doc["temperature_c"] == 42.625


def test_status_drops_sections_the_charger_omits(fake_charger, capsys) -> None:
    """Firmware that publishes no socket states must not fake one."""
    fake_charger.docs["/api/status-props"] = []
    assert cli.main(["status", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Socket" not in out and "Temperature" not in out
    assert "Limits" in out  # what it did report is still shown


def test_status_json_omits_what_is_missing(fake_charger, capsys) -> None:
    fake_charger.docs["/api/status-props"] = []
    assert cli.main(["status", "--json", "--host", "1.2.3.4"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["sockets"] == []
    assert "temperature_c" not in doc


# --- Wi-Fi scan --------------------------------------------------------------------------------


def test_wifi_scan_table(fake_charger, capsys) -> None:
    fake_charger.docs["/api/wifiscan"] = [
        {"Ssid": "home-net", "SignalStrength": -45, "Security": 4194308, "Band": 5},
        {"Ssid": "guest", "SignalStrength": -70, "Security": 0, "Band": 2},
    ]
    assert cli.main(["wifi", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "home-net" in out
    assert "WPA2-PSK (AES)" in out
    assert "2 network(s)" in out


def test_wifi_scan_json(fake_charger, capsys) -> None:
    fake_charger.docs["/api/wifiscan"] = [
        {"Ssid": "home-net", "SignalStrength": -45, "Security": 4194308}
    ]
    assert cli.main(["wifi", "--json", "--host", "1.2.3.4"]) == 0
    (doc,) = json.loads(capsys.readouterr().out)
    assert doc["ssid"] == "home-net"
    assert doc["security"] == "WPA2-PSK (AES)"


def test_wifi_scan_empty(fake_charger, capsys) -> None:
    assert cli.main(["wifi", "--host", "1.2.3.4"]) == 0
    assert "No Wi-Fi networks found" in capsys.readouterr().out


def _radio(fake_charger, *, enabled: int, status: int) -> None:
    """Give the charger a Wi-Fi radio in a particular state."""
    fake_charger.docs["/api/prop"]["properties"] += [
        {"id": "328F_0", "access": 1, "type": 5, "value": 1},
        {"id": "3284_0", "access": 2, "type": 5, "value": enabled},
        {"id": "328E_0", "access": 2, "type": 5, "value": status},
    ]


@pytest.fixture(autouse=True)
def impatient(monkeypatch):
    """Do not really wait on a fake radio: no boot to sit through, no rescan."""
    monkeypatch.setattr(net, "RADIO_READY_TIMEOUT_S", 0.0)
    monkeypatch.setattr(netcmd, "SCAN_RETRY_INTERVAL_S", 0.0)


def test_an_empty_scan_says_when_the_radio_is_off(fake_charger, capsys) -> None:
    """The commonest reason for "no networks found" is nobody listening."""
    _radio(fake_charger, enabled=0, status=net.WIFI_DISABLED)
    assert cli.main(["wifi", "scan", "--host", "1.2.3.4"]) == 0
    captured = capsys.readouterr()
    assert "No Wi-Fi networks found" in captured.out
    assert "switched off" in captured.err
    assert "wifi scan --enable" in captured.err
    assert fake_charger.writes == []


def test_an_empty_scan_with_a_running_radio_is_left_alone(fake_charger, capsys) -> None:
    _radio(fake_charger, enabled=1, status=net.WIFI_RUNNING)
    assert cli.main(["wifi", "scan", "--host", "1.2.3.4"]) == 0
    assert "switched off" not in capsys.readouterr().err


def test_scan_enable_switches_the_radio_on_first(
    fake_charger, capsys, impatient
) -> None:
    _radio(fake_charger, enabled=0, status=net.WIFI_DISABLED)
    fake_charger.docs["/api/wifiscan"] = [
        {"Ssid": "home-net", "SignalStrength": -45, "Security": 4194308}
    ]
    assert cli.main(["wifi", "scan", "--enable", "--host", "1.2.3.4"]) == 0
    assert any(net.P_WIFI_ENABLED in w for w in fake_charger.writes)
    assert "home-net" in capsys.readouterr().out


def test_wifi_enable_writes_only_the_flag(fake_charger, capsys, impatient) -> None:
    _radio(fake_charger, enabled=0, status=net.WIFI_DISABLED)
    assert cli.main(["wifi", "enable", "--host", "1.2.3.4"]) == 0
    (write,) = [w for w in fake_charger.writes if net.P_WIFI_ENABLED in w]
    assert set(write) == {net.P_WIFI_ENABLED}


def test_an_empty_scan_is_asked_again_before_it_is_believed(
    fake_charger, capsys
) -> None:
    """The charger reports the survey it has, which just after a boot is none."""
    _radio(fake_charger, enabled=1, status=net.WIFI_RUNNING)
    calls: list[int] = []

    def scan() -> str:
        calls.append(1)
        if len(calls) > 1:
            return json.dumps(
                {
                    "scan_results": [
                        {"Ssid": "home-net", "SignalStrength": -45, "Security": 4194308}
                    ]
                }
            )
        return json.dumps({"scan_results": []})

    fake_charger.wifi_scan = scan
    assert cli.main(["wifi", "scan", "--host", "1.2.3.4"]) == 0
    assert len(calls) == 2
    assert "home-net" in capsys.readouterr().out


def test_one_attempt_asks_once(fake_charger, capsys) -> None:
    _radio(fake_charger, enabled=1, status=net.WIFI_RUNNING)
    calls: list[int] = []
    fake_charger.wifi_scan = lambda: (calls.append(1), '{"scan_results": []}')[1]
    assert cli.main(["wifi", "scan", "--attempts", "1", "--host", "1.2.3.4"]) == 0
    assert len(calls) == 1


def test_a_reply_that_is_not_a_scan_result_says_so(fake_charger, capsys) -> None:
    """A parser that did not understand the answer must not report an empty band."""
    _radio(fake_charger, enabled=1, status=net.WIFI_RUNNING)
    fake_charger.wifi_scan = lambda: "<html>Not found</html>"
    assert cli.main(["wifi", "scan", "--host", "1.2.3.4"]) == 0
    err = capsys.readouterr().err
    assert "not JSON" in err and "--debug" in err


def test_an_empty_band_with_a_running_radio_says_what_to_check(
    fake_charger, capsys
) -> None:
    _radio(fake_charger, enabled=1, status=net.WIFI_RUNNING)
    err = (cli.main(["wifi", "scan", "--host", "1.2.3.4"]), capsys.readouterr().err)[1]
    assert "5 GHz" in err and "heard nothing" in err


def test_wifi_enable_refuses_a_station_with_no_radio(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += [
        {"id": "328F_0", "access": 1, "type": 5, "value": 0}
    ]
    assert cli.main(["wifi", "enable", "--host", "1.2.3.4"]) != 0
    assert "no Wi-Fi radio" in capsys.readouterr().err
    assert fake_charger.writes == []


# --- Smart-meter test ----------------------------------------------------------------------


def test_meter_test_table(fake_charger, capsys) -> None:
    fake_charger.docs["/api/meter4"] = [
        {"id": "5221_A", "value": 10.0},
        {"id": "5221_13", "value": 2300.0},
    ]
    assert cli.main(["meter-test", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Current L1" in out and "10.0 A" in out
    assert "Active power L1" in out and "2.3 kW" in out


def test_meter_test_json(fake_charger, capsys) -> None:
    fake_charger.docs["/api/meter4"] = [{"id": "5221_A", "value": 10.0}]
    assert cli.main(["meter-test", "--json", "--host", "1.2.3.4"]) == 0
    doc = json.loads(capsys.readouterr().out)
    by_label = {r["label"]: r for r in doc}
    assert by_label["Current L1"]["value"] == 10.0


def test_meter_test_no_readings_errors(fake_charger, capsys) -> None:
    assert cli.main(["meter-test", "--host", "1.2.3.4"]) == 1
    assert "Modbus" in capsys.readouterr().err


# --- Live status --------------------------------------------------------------------------


def test_status_watch_redraws_until_interrupted(
    fake_charger, capsys, monkeypatch
) -> None:
    rounds: list[int] = []

    def fake_sleep(seconds: float) -> None:
        assert seconds == 5
        rounds.append(1)
        if len(rounds) > 1:
            raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep)
    assert cli.main(["status", "--watch", "5", "--host", "1.2.3.4"]) == (
        cli.EXIT_INTERRUPTED
    )
    out = capsys.readouterr().out
    assert out.count("ACE0781464 (NG910-60027)") == 2  # one per redraw
    assert "updated " in out


def test_status_watch_defaults_its_interval(fake_charger, capsys, monkeypatch) -> None:
    seen: list[float] = []

    def fake_sleep(seconds: float) -> None:
        seen.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep)
    assert cli.main(["status", "--watch", "--host", "1.2.3.4"]) == (
        cli.EXIT_INTERRUPTED
    )
    assert seen == [cli.DEFAULT_WATCH_INTERVAL_S]


# --- Hardware details in info ---------------------------------------------------------------


def test_info_shows_hardware_and_clock(fake_charger, capsys) -> None:

    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    fake_charger.docs["/api/prop"]["properties"] += [
        {"id": "204D_1", "value": 3},  # revision C
        {"id": "204D_2", "value": 4},  # assembly 03
        {"id": "3182_0", "value": "1.4.0"},
        {"id": "3180_0", "value": "HW:2.1,SW:3.5"},
        {"id": "2118_0", "value": "Quectel"},
        {"id": "2119_0", "value": "EG25"},
        {"id": "2121_0", "value": "860123456789012"},
        {"id": "2059_0", "value": now},
    ]
    assert cli.main(["info", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Controller board" in out and "C-03" in out
    assert "Bootloader" in out and "1.4.0" in out
    assert "RFID reader" in out and "hardware 2.1, software 3.5" in out
    assert "Quectel EG25" in out
    assert "860123456789012" in out
    assert "Clock" in out and "UTC" in out


def test_info_omits_hardware_the_charger_does_not_report(fake_charger, capsys) -> None:
    assert cli.main(["info", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Controller board" not in out
    assert "RFID reader" not in out
    assert "Clock" not in out
