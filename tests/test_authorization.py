"""Authorization: the mode, the two lists, and the offline action's two halves.

The setting worth testing is the offline action, which the app presents as
one dropdown and the charger stores as two separate booleans.  Getting the
pair back out is easy; putting it back in without ever writing the one
combination the vendor's enumeration does not define is the part that needs a
test.
"""

from __future__ import annotations

import pytest

from alfenctl import authorization as auth
from alfenctl.charger import LiveProperty


class FakeCharger:
    """Holds the registers this module reads, and records what it writes."""

    def __init__(self, values: dict[tuple[int, int], object]) -> None:
        self.values = dict(values)
        self.writes: list[dict] = []

    def fetch_properties_by_ids(self, keys):
        return [
            LiveProperty(id=f"{p:X}_{s:X}", key=(p, s), value=self.values[(p, s)])
            for p, s in keys
            if (p, s) in self.values
        ]

    def write_properties(self, writes):
        self.writes.append(dict(writes))
        for key, (value, _type) in writes.items():
            self.values[key] = value


def charger(overrides: dict | None = None) -> FakeCharger:
    """An RFID station consulting its whitelist, refusing tags while offline."""
    values: dict[tuple[int, int], object] = {
        auth.P_MODE: auth.MODE_RFID,
        auth.P_WHITELIST_ENABLED: 1,
        auth.P_LOCAL_LIST_ENABLED: 0,
        auth.P_OFFLINE_HIGH: 0,
        auth.P_OFFLINE_LOW: 0,
        auth.P_ONLINE_ACTION: 0,
        auth.P_MAX_OUTAGE_S: 60,
        auth.P_PLUG_AND_CHARGE_ID: "",
    }
    values.update(overrides or {})
    return FakeCharger(values)


# --- the offline action is two registers ------------------------------------


@pytest.mark.parametrize(
    ("high", "low", "expected"),
    [
        (0, 0, auth.OFFLINE_REFUSE_ALL),
        (0, 1, auth.OFFLINE_ACCEPT_KNOWN),
        (1, 1, auth.OFFLINE_ACCEPT_ALL),
    ],
)
def test_the_offline_pair_reads_as_one_value(high, low, expected) -> None:
    state = auth.read(charger({auth.P_OFFLINE_HIGH: high, auth.P_OFFLINE_LOW: low}))
    assert state.offline_action == expected


@pytest.mark.parametrize(
    ("action", "high", "low"),
    [
        (auth.OFFLINE_REFUSE_ALL, 0, 0),
        (auth.OFFLINE_ACCEPT_KNOWN, 0, 1),
        (auth.OFFLINE_ACCEPT_ALL, 1, 1),
    ],
)
def test_the_offline_value_writes_back_to_both_halves(action, high, low) -> None:
    c = charger()
    auth.apply(c, offline_action=action)
    assert c.values[auth.P_OFFLINE_HIGH] == high
    assert c.values[auth.P_OFFLINE_LOW] == low


def test_the_offline_action_round_trips() -> None:
    c = charger()
    for action in auth.OFFLINE_ACTIONS:
        assert auth.apply(c, offline_action=action).offline_action == action


def test_the_undefined_offline_combination_is_never_written() -> None:
    c = charger()
    with pytest.raises(auth.AuthorizationError):
        auth.apply(c, offline_action=2)
    assert c.writes == []


def test_a_station_already_holding_the_undefined_pair_is_reported() -> None:
    """Reading is permissive where writing is not: say what is there."""
    state = auth.read(charger({auth.P_OFFLINE_HIGH: 1, auth.P_OFFLINE_LOW: 0}))
    assert state.offline_action == 2
    assert any("does not define" in w for w in state.warnings())


# --- the rest ---------------------------------------------------------------


def test_a_set_sends_exactly_one_batch() -> None:
    c = charger()
    auth.apply(c, mode=auth.MODE_PLUG_AND_CHARGE, whitelist=False, max_outage_s=30)
    assert len(c.writes) == 1
    assert set(c.writes[0]) == {
        auth.P_MODE,
        auth.P_WHITELIST_ENABLED,
        auth.P_MAX_OUTAGE_S,
    }


def test_naming_nothing_writes_nothing() -> None:
    c = charger()
    auth.apply(c)
    assert c.writes == []


@pytest.mark.parametrize(
    "kwargs",
    [{"mode": 1}, {"online_action": 9}, {"max_outage_s": -1}, {"max_outage_s": 99999}],
)
def test_values_outside_the_vendor_enumerations_are_refused(kwargs) -> None:
    c = charger()
    with pytest.raises(auth.AuthorizationError):
        auth.apply(c, **kwargs)
    assert c.writes == []


def test_rfid_with_no_list_enabled_is_a_warning() -> None:
    state = auth.read(
        charger({auth.P_WHITELIST_ENABLED: 0, auth.P_LOCAL_LIST_ENABLED: 0})
    )
    assert any(
        "neither the whitelist nor the local list" in w for w in state.warnings()
    )


def test_plug_and_charge_with_a_whitelist_is_a_warning() -> None:
    state = auth.read(charger({auth.P_MODE: auth.MODE_PLUG_AND_CHARGE}))
    assert any("plug-and-charge authorises" in w for w in state.warnings())


def test_a_charger_that_answers_for_nothing_reports_nothing() -> None:
    state = auth.read(FakeCharger({}))
    assert state.rows() == []
    assert state.warnings() == []
