"""Tests for the charger's knobs: current limits, brightness, clock and charging profiles."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone


from conftest import (
    status_error,
)

from alfenctl import cli


# --- OCPP charging profiles ------------------------------------------------------------------


def test_charging_profiles_list_empty(fake_charger, capsys) -> None:
    assert cli.main(["charging-profiles", "list", "--host", "1.2.3.4"]) == 0
    assert "No charging profiles installed" in capsys.readouterr().out


def test_charging_profiles_list(fake_charger, capsys) -> None:
    fake_charger.docs["/api/chargingprofiles-ids"] = json.dumps(
        {"ChargingProfileIDs": [{"Value": 1}, {"Value": -19061964}]}
    )
    assert cli.main(["charging-profiles", "list", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "1" in out
    assert "-19061964 (UK Smart Charging default)" in out


def test_charging_profiles_list_unsupported_firmware(fake_charger, capsys) -> None:
    fake_charger.charging_profile_error = status_error(404)
    assert cli.main(["charging-profiles", "list", "--host", "1.2.3.4"]) == 1
    assert "does not support charging profiles" in capsys.readouterr().err


def test_charging_profiles_show(fake_charger, capsys) -> None:
    fake_charger.docs["/api/chargingprofiles"] = {
        "42": json.dumps(
            {
                "version": 2,
                "Profile": [
                    {
                        "connectorId": 0,
                        "csChargingProfiles": [
                            {
                                "chargingProfileId": 42,
                                "chargingProfileKind": "Absolute",
                                "chargingProfilePurpose": "TxDefaultProfile",
                                "stackLevel": 0,
                                "chargingSchedule": {
                                    "chargingRateUnit": "A",
                                    "chargingSchedulePeriod": [
                                        {"startPeriod": 0, "limit": 16}
                                    ],
                                },
                            }
                        ],
                    }
                ],
            }
        )
    }
    assert cli.main(["charging-profiles", "show", "42", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Profile 42" in out
    assert "limit 16 A" in out


def test_charging_profiles_show_missing(fake_charger, capsys) -> None:
    assert cli.main(["charging-profiles", "show", "99", "--host", "1.2.3.4"]) == 1
    assert "No charging profile 99" in capsys.readouterr().err


def test_charging_profiles_clear_one(fake_charger, capsys) -> None:
    assert cli.main(["charging-profiles", "clear", "42", "--host", "1.2.3.4"]) == 0
    assert fake_charger.cleared_profiles == [42]
    assert "Cleared charging profile 42" in capsys.readouterr().out


def test_charging_profiles_clear_all(fake_charger, capsys) -> None:
    assert cli.main(["charging-profiles", "clear", "--host", "1.2.3.4"]) == 0
    assert fake_charger.cleared_profiles == ["all"]


def test_charging_profiles_install_uk(fake_charger, capsys) -> None:
    assert cli.main(["charging-profiles", "install-uk", "--host", "1.2.3.4"]) == 0
    assert len(fake_charger.added_profiles) == 1
    profile = fake_charger.added_profiles[0]
    assert profile["csChargingProfiles"]["chargingProfileId"] == -19061964
    assert "blocked" in capsys.readouterr().out


# --- Clock --------------------------------------------------------------------------------


def _clock_props(
    epoch_ms: int, *, minutes: int | None = 60, dst: int = 1
) -> list[dict]:
    props = [
        {"id": "2059_0", "value": epoch_ms},
        {"id": "205B_0", "value": dst},
    ]
    if minutes is not None:
        props.append({"id": "206E_0", "value": minutes})
    return props


def test_time_show_reports_the_drift(fake_charger, capsys) -> None:

    stale = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    fake_charger.docs["/api/prop"]["properties"] += _clock_props(stale)
    assert cli.main(["time", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "2020-01-01 00:00:00" in out
    assert "years behind this computer" in out
    assert "UTC+01:00, daylight saving on" in out
    assert "alfenctl time sync" in out


def test_time_show_without_a_clock(fake_charger, capsys) -> None:
    assert cli.main(["time", "show", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "<not reported>" in out
    assert "charger reports no time" in out


def test_time_show_falls_back_to_the_six_minute_zone(fake_charger, capsys) -> None:
    """Older firmware carries only sysTimeZone, counted in six-minute steps."""

    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    fake_charger.docs["/api/prop"]["properties"] += _clock_props(now, minutes=None)
    fake_charger.docs["/api/prop"]["properties"].append(
        {"id": "205A_0", "value": 20}  # 20 * 6 minutes == UTC+02:00
    )
    assert cli.main(["time", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "UTC+02:00" in out
    assert "in sync with this computer" in out
    assert "alfenctl time sync" not in out  # nothing to fix, so no nudge


def test_time_sync_sets_the_clock(fake_charger, capsys) -> None:

    stale = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    fake_charger.docs["/api/prop"]["properties"] += _clock_props(stale)
    assert cli.main(["time", "sync", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "ACE0781464's clock set to" in out
    assert "years behind" in out
    assert fake_charger.synced is not None


# --- Current limits and brightness ---------------------------------------------------------


def _control_props() -> list[dict]:
    """A two-socket station at 32 A, both sockets at 16 A, LEDs at half."""
    return [
        {"id": "2129_0", "access": 2, "type": 8, "value": 16.0},
        {"id": "3129_0", "access": 2, "type": 8, "value": 16.0},
        {"id": "2061_1", "access": 2, "type": 2, "value": 1},
        {"id": "2061_2", "access": 2, "type": 2, "value": 50},
    ]


def test_current_show_lists_every_limit(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _control_props()
    assert cli.main(["current", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Station maximum" in out and "25 A" in out  # 2062_0 in LIVE_DOCS
    assert "Socket 1 maximum  16 A" in out
    assert "Socket 2 maximum  16 A" in out
    assert "alfenctl current set" in out


def test_current_set_writes_every_socket(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _control_props()
    assert cli.main(["current", "set", "10", "--host", "1.2.3.4"]) == 0
    written = fake_charger.writes[0]
    assert written[(0x2129, 0)][0] == 10.0
    assert written[(0x3129, 0)][0] == 10.0
    assert "Socket 1, Socket 2 set to 10 A." in capsys.readouterr().out


def test_current_set_can_name_one_socket(fake_charger) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _control_props()
    assert cli.main(["current", "set", "8", "--socket", "2", "--host", "1.2.3.4"]) == 0
    written = fake_charger.writes[0]
    assert (0x2129, 0) not in written
    assert written[(0x3129, 0)][0] == 8.0


def test_current_set_station_max_warns_when_a_socket_now_exceeds_it(
    fake_charger, capsys
) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _control_props()
    rc = cli.main(["current", "set", "10", "--station-max", "--host", "1.2.3.4"])
    assert rc == 0
    assert fake_charger.writes[0][(0x2062, 0)][0] == 10.0
    err = capsys.readouterr().err
    assert "socket 1 is set to 16 A" in err


def test_current_set_refuses_an_impossible_value(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _control_props()
    assert cli.main(["current", "set", "0", "--host", "1.2.3.4"]) != 0
    assert "must be between" in capsys.readouterr().err
    assert fake_charger.writes == []


def test_brightness_show_and_set(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _control_props()
    assert cli.main(["brightness", "--host", "1.2.3.4"]) == 0
    assert "Intensity  50%" in capsys.readouterr().out
    assert (
        cli.main(["brightness", "set", "20", "--auto", "off", "--host", "1.2.3.4"]) == 0
    )
    written = fake_charger.writes[0]
    assert written[(0x2061, 2)][0] == 20
    assert written[(0x2061, 1)][0] == 0
    assert "Intensity  20%" in capsys.readouterr().out


def test_brightness_set_needs_something_to_set(fake_charger, capsys) -> None:
    assert cli.main(["brightness", "set", "--host", "1.2.3.4"]) != 0
    assert "give a brightness" in capsys.readouterr().err


# --- the external request, and taking a socket out of service ---------------------------------


def _live_current_props() -> list[dict]:
    """The RAM registers a dynamic controller drives, plus what is in force."""
    return [
        {"id": "212A_0", "access": 2, "type": 8, "value": 10.0},
        {"id": "212B_0", "access": 1, "type": 8, "value": 16.0},
        {"id": "212C_0", "access": 1, "type": 8, "value": 12.0},
    ]


def test_current_show_separates_what_is_asked_from_what_is_configured(
    fake_charger, capsys
) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _control_props()
    fake_charger.docs["/api/prop"]["properties"] += _live_current_props()
    assert cli.main(["current", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Socket 1 maximum" in out
    assert "external request" in out and "10 A" in out
    assert "16 A static, 12 A active" in out


def test_current_set_external_writes_the_ram_register(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _control_props()
    fake_charger.docs["/api/prop"]["properties"] += _live_current_props()
    rc = cli.main(
        ["current", "set", "6", "--socket", "1", "--external", "--host", "1.2.3.4"]
    )
    assert rc == 0
    written = fake_charger.writes[0]
    assert written[(0x212A, 0)][0] == 6.0
    assert (0x2129, 0) not in written
    assert "forgets it on the next boot" in capsys.readouterr().out


def test_current_set_external_is_not_a_station_setting(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _control_props()
    rc = cli.main(
        ["current", "set", "6", "--station-max", "--external", "--host", "1.2.3.4"]
    )
    assert rc != 0
    assert "applies to a socket" in capsys.readouterr().err
    assert fake_charger.writes == []


def test_socket_show_reports_the_bit_field(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _control_props()
    fake_charger.docs["/api/prop"]["properties"].append(
        {"id": "205F_0", "access": 2, "type": 7, "value": 4}
    )
    assert cli.main(["socket", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Station" in out
    assert re.search(r"Socket 1\s+in service", out)
    assert re.search(r"Socket 2\s+out of service", out)


def test_socket_disable_needs_a_confirmation(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    fake_charger.docs["/api/prop"]["properties"].append(
        {"id": "205F_0", "access": 2, "type": 7, "value": 0}
    )
    assert cli.main(["socket", "disable", "1", "--host", "1.2.3.4"]) != 0
    assert "Aborted" in capsys.readouterr().err
    assert fake_charger.writes == []


def test_socket_disable_leaves_the_other_socket_alone(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"].append(
        {"id": "205F_0", "access": 2, "type": 7, "value": 2}  # socket 1 already out
    )
    rc = cli.main(["socket", "disable", "2", "-y", "--host", "1.2.3.4"])
    assert rc == 0
    assert fake_charger.writes[0][(0x205F, 0)] == (6, 7)
    assert "Socket 2 is out of service." in capsys.readouterr().out


def test_socket_enable_on_a_station_without_the_register(fake_charger, capsys) -> None:
    assert cli.main(["socket", "enable", "1", "--host", "1.2.3.4"]) != 0
    assert "0x205F_0" in capsys.readouterr().err


# --- direct start ------------------------------------------------------------------------------


def _override_props() -> list[dict]:
    return [
        {"id": "3278_1", "access": 2, "type": 5, "value": 0},
        {"id": "3278_2", "access": 2, "type": 5, "value": 0},
        {"id": "21B9_0", "access": 2, "type": 7, "value": 600},
    ]


def test_direct_start_show(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _override_props()
    assert cli.main(["direct-start", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "follow profile" in out
    assert "600 s" in out


def test_direct_start_on_warns_when_no_profile_is_installed(
    fake_charger, capsys
) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _override_props()
    assert cli.main(["direct-start", "on", "--socket", "1", "--host", "1.2.3.4"]) == 0
    assert fake_charger.writes[0][(0x3278, 1)] == (1, 5)
    assert "no charging profile is installed" in capsys.readouterr().err


def test_direct_start_on_is_quiet_when_a_profile_is_there(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _override_props()
    fake_charger.docs["/api/chargingprofiles-ids"] = json.dumps(
        {"ChargingProfileIDs": [{"Value": -19061964}]}
    )
    assert cli.main(["direct-start", "on", "--host", "1.2.3.4"]) == 0
    assert "no charging profile" not in capsys.readouterr().err
    assert fake_charger.writes[0][(0x3278, 1)] == (1, 5)
    assert fake_charger.writes[0][(0x3278, 2)] == (1, 5)


def test_direct_start_missing_on_older_firmware(fake_charger, capsys) -> None:
    assert cli.main(["direct-start", "--host", "1.2.3.4"]) != 0
    assert "does not carry the charging-profile override" in capsys.readouterr().err
