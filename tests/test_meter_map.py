"""Tests for the custom Modbus register map (read, parse, and the bracketed write)."""

from __future__ import annotations

import json

import pytest

from alfenctl import meter_map


class FakeCharger:
    """Just enough of AlfenCharger for the register-map module."""

    def __init__(self, values: dict) -> None:
        self.values = dict(values)
        self.writes: list[dict] = []
        self.fail_arrays = False

    def fetch_properties_by_ids(self, keys):
        from alfenctl.charger import LiveProperty

        return [
            LiveProperty(id="", key=key, value=self.values[key])
            for key in keys
            if key in self.values
        ]

    def write_properties(self, writes):
        if self.fail_arrays and meter_map.P_KEYS in writes:
            raise RuntimeError("charger refused the arrays")
        self.writes.append(dict(writes))


# Two entries in four slots: current L1 (register 0x0006, u32, x0.001) and
# real power L1 (0x0010, float32, x1); the rest of each array is unused.
LIVE = {
    meter_map.P_KEYS: "07,10,FF,FF",
    meter_map.P_REGISTERS: "0006,0010,0000,0000",
    meter_map.P_DATA_TYPES: "03,06,00,00",
    meter_map.P_SCALES: "FD,00,00,00",  # -3, 0
    meter_map.P_LOAD_BALANCING: 1,
    meter_map.P_MODBUS_BALANCE_MODE: 0,
}

PRESET = json.dumps(
    {
        "Name": "Test meter",
        "Regmap": [
            {
                "Key": "CURRENT_L1",
                "RegNum": 6,
                "DataType": "UNSIGNED32",
                "ScaleE": -3,
            },
            {
                "Key": "POWER_REAL_L1",
                "RegNum": 16,
                "DataType": "FLOAT32",
                "ScaleE": 0,
            },
        ],
    }
)


def test_read_decodes_the_used_slots() -> None:
    regmap = meter_map.read(FakeCharger(LIVE))
    assert regmap.capacity == 4
    assert [e.measurand for e in regmap.entries] == ["CURRENT_L1", "POWER_REAL_L1"]
    first = regmap.entries[0]
    assert (first.register, first.data_type, first.scale) == (6, "UNSIGNED32", -3)
    assert first.factor == "x 0.001"


def test_read_keeps_an_unknown_code_as_a_number() -> None:
    charger = FakeCharger({**LIVE, meter_map.P_KEYS: "FE,10,FF,FF"})
    assert meter_map.read(charger).entries[0].measurand == "<254>"


def test_read_without_the_property() -> None:
    with pytest.raises(meter_map.MeterMapError, match="2570_0"):
        meter_map.read(FakeCharger({}))


def test_parse_json_round_trips() -> None:
    regmap = meter_map.parse_json(PRESET)
    assert regmap.name == "Test meter"
    assert len(regmap.entries) == 2
    again = meter_map.parse_json(meter_map.to_json(regmap))
    assert again.entries == regmap.entries


@pytest.mark.parametrize(
    "doc, message",
    [
        ("not json at all", "not a register-map file"),
        ('{"Name": "x"}', "no 'Regmap' list"),
        ('{"Regmap": []}', "empty"),
        (
            '{"Regmap": [{"Key": "NOPE", "RegNum": 1, "DataType": "FLOAT32", '
            '"ScaleE": 0}]}',
            "unknown measurand",
        ),
        (
            '{"Regmap": [{"Key": "CURRENT_L1", "RegNum": 1, "DataType": "F32", '
            '"ScaleE": 0}]}',
            "unknown data type",
        ),
        (
            '{"Regmap": [{"Key": "CURRENT_L1", "RegNum": 99999, "DataType": '
            '"FLOAT32", "ScaleE": 0}]}',
            "out of range",
        ),
        ('{"Regmap": [{"RegNum": 1}]}', "malformed"),
    ],
)
def test_parse_json_rejects_bad_input(doc: str, message: str) -> None:
    with pytest.raises(meter_map.MeterMapError, match=message):
        meter_map.parse_json(doc)


def test_apply_pads_and_brackets_the_write() -> None:
    charger = FakeCharger(LIVE)
    meter_map.apply(charger, meter_map.parse_json(PRESET), capacity=4)
    # Modbus balancing into socket mode, load balancing off, arrays, back on.
    assert charger.writes[0] == {meter_map.P_MODBUS_BALANCE_MODE: (2, 5)}
    assert charger.writes[1] == {meter_map.P_LOAD_BALANCING: (0, 5)}
    arrays = charger.writes[2]
    assert arrays[meter_map.P_KEYS][0] == bytes([7, 16, 0xFF, 0xFF])
    assert arrays[meter_map.P_REGISTERS][0] == [6, 16, 0, 0]
    assert arrays[meter_map.P_DATA_TYPES][0] == bytes([3, 6, 0, 0])
    assert arrays[meter_map.P_SCALES][0] == bytes([0xFD, 0, 0, 0])  # -3 as a byte
    assert charger.writes[3] == {meter_map.P_LOAD_BALANCING: (1, 5)}  # what it was


def test_apply_restores_load_balancing_even_when_the_write_fails() -> None:
    charger = FakeCharger(LIVE)
    charger.fail_arrays = True
    with pytest.raises(RuntimeError):
        meter_map.apply(charger, meter_map.parse_json(PRESET), capacity=4)
    assert charger.writes[-1] == {meter_map.P_LOAD_BALANCING: (1, 5)}


def test_apply_defaults_the_mode_the_app_restores() -> None:
    """With no readable sysLoadBalancingMode, fall back to the app's own 3."""
    values = {k: v for k, v in LIVE.items() if k != meter_map.P_LOAD_BALANCING}
    charger = FakeCharger(values)
    meter_map.apply(charger, meter_map.parse_json(PRESET), capacity=4)
    assert charger.writes[-1] == {meter_map.P_LOAD_BALANCING: (3, 5)}


def test_apply_skips_the_balance_mode_the_charger_lacks() -> None:
    values = {k: v for k, v in LIVE.items() if k != meter_map.P_MODBUS_BALANCE_MODE}
    charger = FakeCharger(values)
    meter_map.apply(charger, meter_map.parse_json(PRESET), capacity=4)
    assert meter_map.P_MODBUS_BALANCE_MODE not in charger.writes[0]


def test_apply_refuses_a_map_larger_than_the_charger_holds() -> None:
    charger = FakeCharger(LIVE)
    with pytest.raises(meter_map.MeterMapError, match="charger holds"):
        meter_map.apply(charger, meter_map.parse_json(PRESET), capacity=1)
