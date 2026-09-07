"""Load balancing: the mode bit field, the licence gate, and the solar block.

The property writes are one line each.  What is worth testing is what the
charger will not check for itself: that turning one mode bit on leaves the
other alone, that a setting switched on without the licence behind it is
reported rather than silently ignored, and that the solar boost is per socket.
"""

from __future__ import annotations

import pytest

from alfenctl import loadbalancing as lb
from alfenctl.charger import ChargerInfo, LiveProperty


class FakeCharger:
    """Holds the registers this module reads, and records what it writes."""

    def __init__(self, values: dict[tuple[int, int], object]) -> None:
        self.values = dict(values)
        self.writes: list[dict] = []
        self.firmware = "7.4.5-4415"

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

    def basic_info(self) -> ChargerInfo:
        return ChargerInfo(
            object_id="ACE0000001",
            identity="test",
            model="NG910-60027",
            family="NG9",
            firmware=self.firmware,
            firmware_version=(7, 4, 5),
            sockets=2,
        )


def charger(overrides: dict | None = None) -> FakeCharger:
    """An actively balanced station on a Modbus TCP meter, no solar."""
    values: dict[tuple[int, int], object] = {
        lb.P_MODE: lb.ACTIVE_BIT,
        lb.P_MAX_METER_CURRENT: 25.0,
        lb.P_SAFE_CURRENT: 6.0,
        lb.P_PHASE_ROTATION: "L1L2L3",
        lb.P_PROTOCOL: 4,
        lb.P_DATA_SOURCE: 0,
        lb.P_MAX_ALLOWED_PHASES: 3,
        lb.P_PHASE_SWITCHING: 0,
        lb.P_SOLAR_MODE: 0,
        lb.P_SOLAR_GREEN_SHARE: 70,
        lb.P_SOLAR_COMFORT_LEVEL: 1400,
        lb.SOLAR_BOOST[1]: 0,
        lb.SOLAR_BOOST[2]: 0,
        (0x21A0, 0): "unique",
        (0x21A1, 0): "AAAA.BBBB.CCCC.DDDD.EEEE.FFFF",
        # The licence bitmask: SCN, static and active balancing all present.
        (0x21A2, 0): 0x1 | 0x2 | 0x4,
    }
    values.update(overrides or {})
    return FakeCharger(values)


# --- the mode is a bit field, not an enumeration ----------------------------


def test_reading_the_mode_splits_the_two_bits() -> None:
    state = lb.read(charger({lb.P_MODE: lb.STATIC_BIT | lb.ACTIVE_BIT}))
    assert (state.static, state.active) == (True, True)
    assert state.mode_label == "static + active"

    state = lb.read(charger({lb.P_MODE: 0}))
    assert (state.static, state.active) == (False, False)
    assert state.mode_label == "off"


def test_turning_static_on_leaves_active_alone() -> None:
    """The whole point of reading before writing this register."""
    c = charger({lb.P_MODE: lb.ACTIVE_BIT})
    lb.apply(c, static=True)
    assert c.values[lb.P_MODE] == lb.STATIC_BIT | lb.ACTIVE_BIT


def test_turning_active_off_leaves_static_alone() -> None:
    c = charger({lb.P_MODE: lb.STATIC_BIT | lb.ACTIVE_BIT})
    lb.apply(c, active=False)
    assert c.values[lb.P_MODE] == lb.STATIC_BIT


def test_both_bits_can_move_in_one_write() -> None:
    c = charger({lb.P_MODE: lb.STATIC_BIT})
    lb.apply(c, static=False, active=True)
    assert c.values[lb.P_MODE] == lb.ACTIVE_BIT


# --- one round trip ---------------------------------------------------------


def test_a_set_sends_exactly_one_batch() -> None:
    c = charger()
    lb.apply(c, safe_current_a=10.0, max_meter_current_a=32.0, protocol=6)
    assert len(c.writes) == 1
    assert set(c.writes[0]) == {
        lb.P_SAFE_CURRENT,
        lb.P_MAX_METER_CURRENT,
        lb.P_PROTOCOL,
    }


def test_naming_nothing_writes_nothing() -> None:
    c = charger()
    lb.apply(c)
    assert c.writes == []


# --- validation -------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"protocol": 99},
        {"data_source": 7},
        {"phase_rotation": "L4"},
        {"max_allowed_phases": 2},
        {"solar_mode": 5},
        {"solar_green_share": 101},
        {"solar_comfort_w": 100},
        {"safe_current_a": 1000.0},
        {"solar_boost": {3: True}},
    ],
)
def test_values_the_charger_would_take_but_cannot_use_are_refused(kwargs) -> None:
    c = charger()
    with pytest.raises(lb.LoadBalancingError):
        lb.apply(c, **kwargs)
    assert c.writes == []


def test_phase_rotation_is_written_as_a_string() -> None:
    c = charger()
    lb.apply(c, phase_rotation="L2L3L1")
    assert c.values[lb.P_PHASE_ROTATION] == "L2L3L1"


# --- solar ------------------------------------------------------------------


def test_solar_boost_is_per_socket() -> None:
    c = charger()
    lb.apply(c, solar_boost={2: True})
    assert c.values[lb.SOLAR_BOOST[1]] == 0
    assert c.values[lb.SOLAR_BOOST[2]] == 1


def test_solar_rows_appear_once_the_mode_is_set() -> None:
    state = lb.read(charger({lb.P_SOLAR_MODE: lb.SOLAR_GREEN}))
    labels = dict(state.rows())
    assert labels["Solar charging"] == "green"
    assert labels["  green share"] == "70%"


# --- the licence gate -------------------------------------------------------


def test_a_mode_without_its_licence_is_a_warning() -> None:
    state = lb.read(
        charger({lb.P_MODE: lb.ACTIVE_BIT, (0x21A2, 0): 0x2})  # static only
    )
    assert any("active load balancing is on" in w for w in state.warnings())


def test_old_firmware_has_every_feature_and_no_warning() -> None:
    """Below the licensing floor there is no bitmask, and nothing is locked."""
    c = charger({(0x21A2, 0): 0})
    c.firmware = "3.3.0-1000"
    state = lb.read(c)
    assert state.licensed_active is True
    assert not [w for w in state.warnings() if "licensed" in w]


def test_solar_without_active_balancing_is_a_warning() -> None:
    state = lb.read(charger({lb.P_MODE: 0, lb.P_SOLAR_MODE: lb.SOLAR_GREEN}))
    assert any(
        "solar charging needs active load balancing" in w for w in state.warnings()
    )


def test_an_unknown_protocol_number_still_reads() -> None:
    state = lb.read(charger({lb.P_PROTOCOL: 42}))
    assert dict(state.rows())["Meter protocol"] == "unknown (42)"
