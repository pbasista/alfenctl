"""Tests for the smart-meter wiring test module."""

from __future__ import annotations

from alfenctl import meter_test


def test_read_scales_currents_and_powers() -> None:
    values = {
        (0x5221, 0xA): 10.234,  # Current L1
        (0x5221, 0xB): 5.0,  # Current L2
        (0x5221, 0xC): 0.0,  # Current L3
        (0x5221, 0x13): 2300.0,  # Active power L1 (W)
        (0x5221, 0x14): 1150,  # Active power L2 (W)
        (0x5221, 0x15): 0,  # Active power L3 (W)
    }
    readings = {r.label: r for r in meter_test.read(values)}
    assert readings["Current L1"].value == 10.23
    assert readings["Current L1"].unit == "A"
    assert readings["Active power L1"].value == 2.3
    assert readings["Active power L1"].unit == "kW"
    assert readings["Active power L3"].value == 0.0


def test_read_reports_none_for_missing_values() -> None:
    readings = meter_test.read({})
    assert len(readings) == 6
    assert all(r.value is None for r in readings)


def test_read_tolerates_unparseable_values() -> None:
    values = {(0x5221, 0xA): "not a number"}
    readings = {r.label: r for r in meter_test.read(values)}
    assert readings["Current L1"].value is None
