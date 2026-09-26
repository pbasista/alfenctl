"""The charger's clock: what "drift" is measured against.

A reading is only as good as the instant it is compared with.  The charger
samples its clock somewhere inside the request, so both ends of the round
trip are wrong: the moment the request was composed is too early, the moment
the answer arrived is too late.  Comparing against the latter is what made a
freshly synced station report a couple of seconds behind.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import httpx
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
    assert clock.format_drift(state.drift()) == "in sync"


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


# --- setting it ---------------------------------------------------------------
# Lifted out of AlfenCharger, which now only carries the two requests: the
# property write and the command the firmware actually acts on.  Choosing the
# moment -- and aiming it far enough ahead that it is right when it lands --
# is this module's business, so it is tested here.


def test_setting_the_clock_sends_date_command(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        clock.set(ch)
        clock.set(ch, is_ahp=True)
    # Like the app's SetDate: sysDateTime first, then tell the firmware.
    assert seen[0].url.path == "/api/prop"
    assert json.loads(seen[0].content)["2059_0"]["value"] > 1_700_000_000_000
    assert seen[1].url.path == "/api/cmd"
    assert json.loads(seen[1].content)["command"].startswith("date 20")
    assert seen[3].url.path == "/api/datetime"
    assert seen[3].content.startswith(b'"20')  # ISO-ish timestamp, JSON-quoted


def test_setting_the_clock_takes_an_explicit_moment(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    when = datetime(2026, 9, 4, 20, 31, 2, tzinfo=timezone.utc)
    with make_charger(handler) as ch:
        clock.set(ch, when)
    assert json.loads(seen[0].content)["2059_0"]["value"] == 1788553862000
    assert json.loads(seen[1].content)["command"] == "date 2026-09-04 20:31:02"


def test_setting_the_clock_survives_a_charger_without_the_property(
    make_charger,
) -> None:
    """Old firmware refuses the property write; the command still goes."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        if request.url.path == "/api/prop" and request.method == "POST":
            return httpx.Response(404)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        clock.set(ch)
    assert [r.url.path for r in seen][-1] == "/api/cmd"


def test_setting_the_clock_stamps_the_command_when_it_is_sent(make_charger) -> None:
    """The command is stamped fresh, not from before the property write.

    The command is what actually moves the clock, and it leaves a whole
    round trip after the method was entered.  Stamping both from one reading
    left the charger that far behind for as long as it ran.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        if request.url.path == "/api/prop":
            time.sleep(1.2)  # a slow charger answering the property write
        return httpx.Response(200)

    entered = datetime.now(timezone.utc)
    with make_charger(handler) as ch:
        sent = clock.set(ch)
    stamp = json.loads(seen[1].content)["command"].removeprefix("date ")
    assert stamp == sent.strftime("%Y-%m-%d %H:%M:%S")
    assert (sent - entered).total_seconds() >= 1.0
