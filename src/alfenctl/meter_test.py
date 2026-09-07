"""Live smart-meter wiring test (the app's Modbus TCP/RTU "Test" dialog).

When commissioning an external kWh meter (Modbus TCP or RTU, used for load
balancing) the app offers a small dialog reading its per-phase current and
power live, so the installer can confirm the wiring and CT orientation
before trusting the meter (``DlgSmartMeterTest``). The six measurands sit at
sub-indices of property ``(0x5221, n)`` (21025) -- a live-only object with
no EDS entry, populated once the ``meter4`` category has been read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

METER_TEST_ID = 0x5221
CATEGORY = "meter4"

# (sub-index, label, unit, decimals, divider) -- ModbusMeasurandUIList.
_MEASURANDS: tuple[tuple[int, str, str, int, int], ...] = (
    (0xA, "Current L1", "A", 2, 1),
    (0xB, "Current L2", "A", 2, 1),
    (0xC, "Current L3", "A", 2, 1),
    (0x13, "Active power L1", "kW", 3, 1000),
    (0x14, "Active power L2", "kW", 3, 1000),
    (0x15, "Active power L3", "kW", 3, 1000),
)


@dataclass(frozen=True)
class Measurand:
    """One live reading from the smart-meter test."""

    label: str
    value: float | None
    unit: str


def read(values: dict[tuple[int, int], Any]) -> list[Measurand]:
    """Build the six readings from a ``(METER_TEST_ID, sub)`` property map."""
    out = []
    for sub, label, unit, decimals, divider in _MEASURANDS:
        raw = values.get((METER_TEST_ID, sub))
        value = None
        if raw is not None:
            try:
                value = round(float(raw) / divider, decimals)
            except (TypeError, ValueError):
                value = None
        out.append(Measurand(label=label, value=value, unit=unit))
    return out
