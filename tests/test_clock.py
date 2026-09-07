"""The charger's clock: what "drift" is measured against.

A reading is only as good as the instant it is compared with.  The charger
samples its clock somewhere inside the request, so both ends of the round
trip are wrong: the moment the request was composed is too early, the moment
the answer arrived is too late.  Comparing against the latter is what made a
freshly synced station report a couple of seconds behind.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from alfenctl import clock
from alfenctl.charger import LiveProperty

NOON = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


class SlowCharger:
    """A charger whose clock is exactly right but answers slowly."""

    def __init__(self, delay: float) -> None:
        self.delay = delay

    def fetch_properties_by_ids(self, keys):
        time.sleep(self.delay / 2)
        now = datetime.now(timezone.utc)  # sampled mid-request, as a charger does
        time.sleep(self.delay / 2)
        return [
            LiveProperty(
                id="2059_0",
                key=clock.P_DATE_TIME,
                value=int(now.timestamp() * 1000),
            )
        ]


def test_drift_is_measured_from_when_the_reading_was_taken() -> None:
    state = clock.Clock(utc=NOON, offset=None, daylight_savings=None, measured_at=NOON)
    assert state.drift() == timedelta(0)
    assert clock.format_drift(state.drift()) == "in sync with this computer"


def test_drift_still_takes_an_explicit_moment() -> None:
    state = clock.Clock(utc=NOON, offset=None, daylight_savings=None, measured_at=NOON)
    drift = state.drift(now=NOON - timedelta(hours=1))
    assert drift == timedelta(hours=1)


def test_drift_falls_back_to_now_without_a_measurement() -> None:
    """A hand-built clock (no round trip behind it) still compares."""
    state = clock.Clock(utc=None, offset=None, daylight_savings=None)
    assert state.drift() is None


@pytest.mark.parametrize("delay", [0.4])
def test_read_does_not_count_the_round_trip_as_drift(delay: float) -> None:
    before = datetime.now(timezone.utc)
    state = clock.read(SlowCharger(delay))
    after = datetime.now(timezone.utc)
    assert state.measured_at is not None
    assert before <= state.measured_at <= after
    drift = state.drift()
    assert drift is not None
    # Half the round trip either way would be ~200 ms; the midpoint cancels it.
    assert abs(drift.total_seconds()) < delay / 4


def test_format_zone_reads_as_one_fact() -> None:
    state = clock.Clock(
        utc=NOON, offset=timedelta(hours=1), daylight_savings=True, measured_at=NOON
    )
    assert clock.format_zone(state) == "UTC+01:00, daylight saving on"


def test_format_zone_without_a_daylight_saving_flag() -> None:
    state = clock.Clock(utc=NOON, offset=timedelta(hours=2), daylight_savings=None)
    assert clock.format_zone(state) == "UTC+02:00"
