"""Tests for OCPP charging-profile parsing and the UK default schedule builder."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from alfenctl import charging_profiles
from alfenctl.charger import LiveProperty
from alfenctl.eds import UNSIGNED8, UNSIGNED32


def test_parse_ids() -> None:
    body = json.dumps({"ChargingProfileIDs": [{"Value": 1}, {"Value": -19061964}]})
    assert charging_profiles.parse_ids(body) == [1, -19061964]


def test_parse_ids_tolerates_bare_values_and_bad_bodies() -> None:
    assert charging_profiles.parse_ids(json.dumps({"ChargingProfileIDs": [1, 2]})) == [
        1,
        2,
    ]
    assert charging_profiles.parse_ids("") == []
    assert charging_profiles.parse_ids("not json") == []
    assert charging_profiles.parse_ids(json.dumps({"other": 1})) == []


def test_parse_profiles_ignores_unversioned_replies() -> None:
    assert charging_profiles.parse_profiles(json.dumps({"version": 1})) == []
    assert charging_profiles.parse_profiles("") == []


def test_parse_profiles_reads_schedule() -> None:
    body = json.dumps(
        {
            "version": 2,
            "Profile": [
                {
                    "connectorId": 0,
                    "csChargingProfiles": [
                        {
                            "chargingProfileId": 42,
                            "chargingProfileKind": "Recurring",
                            "chargingProfilePurpose": "ChargingStationExternalConstraints",
                            "stackLevel": 1,
                            "chargingSchedule": {
                                "startSchedule": "2026-09-01T00:00:00Z",
                                "chargingRateUnit": "A",
                                "chargingSchedulePeriod": [
                                    {"startPeriod": 0, "limit": 32},
                                    {"startPeriod": 28800, "limit": 0},
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )
    profiles = charging_profiles.parse_profiles(body)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.profile_id == 42
    assert p.connector_id == 0
    assert p.kind == "Recurring"
    assert p.charging_rate_unit == "A"
    assert p.start_schedule == "2026-09-01T00:00:00Z"
    assert [(pd.start_period_s, pd.limit_a) for pd in p.periods] == [
        (0, 32.0),
        (28800, 0.0),
    ]
    assert not p.is_uk_default


def test_parse_profiles_recognises_the_uk_default_id() -> None:
    body = json.dumps(
        {
            "version": 2,
            "Profile": [
                {
                    "connectorId": 0,
                    "csChargingProfiles": [
                        {
                            "chargingProfileId": charging_profiles.UK_SMART_CHARGING_ID,
                            "chargingSchedule": {"chargingSchedulePeriod": []},
                        }
                    ],
                }
            ],
        }
    )
    (p,) = charging_profiles.parse_profiles(body)
    assert p.is_uk_default


# --- The UK Smart Charging default profile ----------------------------------------------------


def test_uk_default_profile_starts_on_the_most_recent_monday() -> None:
    # 2026-09-03 is a Thursday; the week's Monday is 2026-08-31.
    now = datetime(2026, 9, 3, 15, 30, tzinfo=timezone.utc)
    profile = charging_profiles.uk_default_profile(now)
    schedule = profile["csChargingProfiles"]["chargingSchedule"]
    assert schedule["startSchedule"] == "2026-08-31T00:00:00Z"


def test_uk_default_profile_starts_on_monday_itself() -> None:
    now = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)  # already a Monday
    profile = charging_profiles.uk_default_profile(now)
    schedule = profile["csChargingProfiles"]["chargingSchedule"]
    assert schedule["startSchedule"] == "2026-08-31T00:00:00Z"


def test_uk_default_profile_shape() -> None:
    profile = charging_profiles.uk_default_profile(
        datetime(2026, 8, 31, tzinfo=timezone.utc)
    )
    assert profile["connectorId"] == 0
    csp = profile["csChargingProfiles"]
    assert csp["chargingProfileId"] == charging_profiles.UK_SMART_CHARGING_ID
    assert csp["chargingProfileKind"] == "Recurring"
    assert csp["recurrencyKind"] == "Weekly"
    assert csp["chargingProfilePurpose"] == "ChargingStationExternalConstraints"
    assert csp["useLocalTime"] is True
    assert csp["useRandomisedDelay"] is True
    assert csp["stackLevel"] == 1
    schedule = csp["chargingSchedule"]
    assert schedule["chargingRateUnit"] == "A"
    periods = schedule["chargingSchedulePeriod"]
    # One initial period plus 4 transitions/day * 5 weekdays.
    assert len(periods) == 1 + 4 * 5
    assert periods[0] == {"startPeriod": 0, "limit": 32}
    # Monday's peak window: blocked 08:00-11:00 and 16:00-22:00.
    assert {"startPeriod": 8 * 3600, "limit": 0} in periods
    assert {"startPeriod": 11 * 3600, "limit": 32} in periods
    assert {"startPeriod": 16 * 3600, "limit": 0} in periods
    assert {"startPeriod": 22 * 3600, "limit": 32} in periods
    # Periods are strictly increasing, as the charger requires.
    starts = [p["startPeriod"] for p in periods]
    assert starts == sorted(starts)
    assert len(set(starts)) == len(starts)


def test_uk_default_profile_matches_the_apps_reference_output() -> None:
    """Byte-for-byte against ``ICUChargingProfiles.AddUkSmartChargingProfile``."""
    profile = charging_profiles.uk_default_profile(
        datetime(2026, 8, 31, tzinfo=timezone.utc)
    )
    schedule = profile["csChargingProfiles"]["chargingSchedule"]
    periods = schedule["chargingSchedulePeriod"]

    day = 86400
    expected = [{"startPeriod": 0, "limit": 32}]
    offset = 0
    for _ in range(5):
        expected += [
            {"startPeriod": offset + 28800, "limit": 0},
            {"startPeriod": offset + 39600, "limit": 32},
            {"startPeriod": offset + 57600, "limit": 0},
            {"startPeriod": offset + 79200, "limit": 32},
        ]
        offset += day
    assert periods == expected


# --- the per-socket override of an installed profile ---------------------------------------


class FakeCharger:
    """Answers the two override registers, and records what is written."""

    def __init__(self, values: dict[tuple[int, int], int]) -> None:
        self.values = dict(values)
        self.types: dict[tuple[int, int], int] = {}
        self.writes: list[dict] = []

    def fetch_properties_by_ids(self, keys):
        return [
            LiveProperty(
                id=f"{p:X}_{s:X}",
                key=(p, s),
                value=self.values[(p, s)],
                data_type=self.types.get((p, s)),
            )
            for p, s in keys
            if (p, s) in self.values
        ]

    def write_properties(self, writes):
        self.writes.append(dict(writes))
        for key, (value, _type) in writes.items():
            self.values[key] = value


def _station(overrides: dict[tuple[int, int], int] | None = None) -> FakeCharger:
    values = {
        charging_profiles.SOCKET_OVERRIDE[1]: 0,
        charging_profiles.SOCKET_OVERRIDE[2]: 0,
        charging_profiles.P_RANDOM_DELAY: 600,
    }
    values.update(overrides or {})
    return FakeCharger(values)


def test_read_direct_start_reports_both_sockets_and_the_delay() -> None:
    state = charging_profiles.read_direct_start(
        _station({charging_profiles.SOCKET_OVERRIDE[2]: 1})
    )
    assert state.overrides == {1: 0, 2: 1}
    assert state.random_delay_s == 600
    assert dict(state.rows())["Socket 2"].startswith("direct start")


def test_turning_direct_start_on_touches_only_that_socket() -> None:
    fake = _station()
    charging_profiles.set_direct_start(fake, sockets={2: True})
    assert fake.writes == [{charging_profiles.SOCKET_OVERRIDE[2]: (1, UNSIGNED8)}]
    assert fake.values[charging_profiles.SOCKET_OVERRIDE[1]] == 0


def test_the_socket_and_the_delay_go_in_one_batch() -> None:
    fake = _station()
    charging_profiles.set_direct_start(fake, sockets={1: True}, random_delay_s=900)
    assert len(fake.writes) == 1
    assert fake.writes[0] == {
        charging_profiles.SOCKET_OVERRIDE[1]: (1, UNSIGNED8),
        charging_profiles.P_RANDOM_DELAY: (900, UNSIGNED32),
    }


def test_a_delay_the_firmware_would_refuse_is_refused_here() -> None:
    with pytest.raises(charging_profiles.ChargingProfileError):
        charging_profiles.set_direct_start(_station(), random_delay_s=3601)


def test_a_short_delay_is_written_but_flagged_as_non_compliant() -> None:
    fake = _station()
    after = charging_profiles.set_direct_start(fake, random_delay_s=60)
    assert fake.values[charging_profiles.P_RANDOM_DELAY] == 60
    assert "not UK" not in dict(after.rows())["Random delay"]
    assert "below the compliant" in dict(after.rows())["Random delay"]


def test_setting_nothing_is_an_error_rather_than_an_empty_write() -> None:
    fake = _station()
    with pytest.raises(charging_profiles.ChargingProfileError):
        charging_profiles.set_direct_start(fake)
    assert fake.writes == []
