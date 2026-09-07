"""Custom Modbus register map for an external energy meter.

Load balancing can read an external kWh meter over Modbus, and the charger
knows a handful of meters by name.  For anything else, the app offers
*Custom register mapping* (``DlgModbusRegisterMap`` over ``ICUModbusRegmap``):
you tell the charger, per measurand, which Modbus register to read, how to
interpret it and what to scale it by.

The map lives in four parallel array properties, one entry per position:

======  ==============  ======================================================
0x2570  bytes           the measurand at this position (:data:`MEASURANDS`),
                        0xFF for an unused slot
0x2571  u16 each        the Modbus register number
0x2572  bytes           how to read it (:data:`DATA_TYPES`)
0x2573  signed bytes    power-of-ten scale factor, e.g. -3 for milli-units
======  ==============  ======================================================

The arrays have a fixed length the charger reports, and unused positions are
padded with 0xFF.  Writing them is not a plain property write: the app
brackets it (``ICUModbusRegmap.WriteToDevice``) by putting Modbus balancing
into socket mode (0x2523_2, when the charger has it), turning load balancing
off (``sysLoadBalancingMode`` 0x2064, a bitmask of static|active), storing
the arrays, and turning balancing back on -- so the firmware picks the new
map up rather than reading half of it.  One deviation: the app always
restores 0x2064 to 3 (static *and* active), while this module puts back
whatever the charger had, so applying a map cannot quietly switch load
balancing on.

Alfen publishes ready-made maps as JSON beside the firmware, in the same
``TCPPresets/``/``RTUPresets/`` folders :mod:`alfenctl.repo` already browses
for settings presets -- ``{"Name": ..., "Regmap": [{"Key", "RegNum",
"DataType", "ScaleE"}, ...]}``, which :func:`parse_json` reads.

Scope: only the "smart meter" block (0x2570) is implemented.  A second block
at 0x2560 exists for a central meter, but the app's two entry points both
open the dialog for a smart meter, and its read and write paths disagree
about which meter type selects the other block -- so that path has most
likely never run, and is not reproduced here on a guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from alfenctl.charger import AlfenCharger
from alfenctl.eds import ARRAY_16, BYTEARRAY, UNSIGNED8
from alfenctl.errors import AlfenError

P_KEYS = (0x2570, 0)  # 9584: which measurand each position carries
P_REGISTERS = (0x2571, 0)  # 9585: the Modbus register number
P_DATA_TYPES = (0x2572, 0)  # 9586: how to read the register
P_SCALES = (0x2573, 0)  # 9587: power-of-ten scale factor
ALL_KEYS = (P_KEYS, P_REGISTERS, P_DATA_TYPES, P_SCALES)

P_LOAD_BALANCING = (0x2064, 0)  # 8292 sysLoadBalancingMode: bit0 static, bit1 active
P_MODBUS_BALANCE_MODE = (0x2523, 2)  # 9507_2 ETCPIPSlaveMode

UNUSED_SLOT = 0xFF  # what the charger stores in a position that holds nothing
LOAD_BALANCING_OFF = 0
LOAD_BALANCING_BOTH = 3  # static|active, the value the app always restores
BALANCE_MODE_SOCKET = 2  # ETCPIPSlaveMode.BALANCEMODE_SOCKET
BYTE_SIGN_BIT = 0x80
BYTE_RANGE = 0x100
MAX_REGISTER = 0xFFFF

# EnergyMeterMeasurand, in its own order: the position in this tuple is the
# value stored in the 0x2570 array.
MEASURANDS = (
    "VOLTAGE_L1N",
    "VOLTAGE_L2N",
    "VOLTAGE_L3N",
    "VOLTAGE_L1L2",
    "VOLTAGE_L2L3",
    "VOLTAGE_L3L1",
    "CURRENT_N",
    "CURRENT_L1",
    "CURRENT_L2",
    "CURRENT_L3",
    "CURRENT_SUM",
    "COSPHI_L1",
    "COSPHI_L2",
    "COSPHI_L3",
    "COSPHI_SUM",
    "FREQUENCY",
    "POWER_REAL_L1",
    "POWER_REAL_L2",
    "POWER_REAL_L3",
    "POWER_REAL_SUM",
    "POWER_APPARENT_L1",
    "POWER_APPARENT_L2",
    "POWER_APPARENT_L3",
    "POWER_APPARENT_SUM",
    "POWER_REACTIVE_L1",
    "POWER_REACTIVE_L2",
    "POWER_REACTIVE_L3",
    "POWER_REACTIVE_SUM",
    "ENERGY_REAL_DELIVERED_L1",
    "ENERGY_REAL_DELIVERED_L2",
    "ENERGY_REAL_DELIVERED_L3",
    "ENERGY_REAL_DELIVERED_SUM",
    "ENERGY_REAL_CONSUMED_L1",
    "ENERGY_REAL_CONSUMED_L2",
    "ENERGY_REAL_CONSUMED_L3",
    "ENERGY_REAL_CONSUMED_SUM",
    "ENERGY_APPARENT_L1",
    "ENERGY_APPARENT_L2",
    "ENERGY_APPARENT_L3",
    "ENERGY_APPARENT_SUM",
    "ENERGY_REACTIVE_L1",
    "ENERGY_REACTIVE_L2",
    "ENERGY_REACTIVE_L3",
    "ENERGY_REACTIVE_SUM",
)

# ModbusDataType, likewise positional.
DATA_TYPES = (
    "SIGNED16",
    "UNSIGNED16",
    "SIGNED32",
    "UNSIGNED32",
    "SIGNED64",
    "UNSIGNED64",
    "FLOAT32",
    "FLOAT64",
)


class MeterMapError(AlfenError, ValueError):
    """The register map cannot be read, parsed, or written as asked."""


@dataclass(frozen=True)
class Entry:
    """One measurand's place in the meter's register space."""

    measurand: str
    register: int
    data_type: str
    scale: int

    @property
    def factor(self) -> str:
        """The scale as a human-readable multiplier ("x 0.001")."""
        return f"x {10.0**self.scale:g}"


@dataclass(frozen=True)
class RegisterMap:
    """A charger's whole custom map, plus where it came from."""

    entries: list[Entry]
    capacity: int | None = None  # how many positions the charger's arrays hold
    name: str = ""  # a preset's own name, when it came from one


def _numbers(raw: Any) -> list[int]:
    """Parse one array property's value into numbers.

    The charger sends these arrays as comma-joined hex ("0A,FF,..."), which
    is also how :func:`alfenctl.charger.encode_property_value` writes them.
    """
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple)):
        return [int(v) for v in raw]
    if isinstance(raw, bytes):
        return list(raw)
    out = []
    for part in str(raw).split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part, 16))
            except ValueError:
                raise MeterMapError(f"cannot read '{raw}' as a hex array") from None
    return out


def _signed(value: int) -> int:
    """Read one byte as a signed scale exponent."""
    return value - BYTE_RANGE if value & BYTE_SIGN_BIT else value


def _name(table: tuple[str, ...], value: int) -> str:
    """Name a measurand or data type, keeping the number if it is unknown."""
    return table[value] if 0 <= value < len(table) else f"<{value}>"


def read(charger: AlfenCharger) -> RegisterMap:
    """Read the register map the charger currently holds."""
    live = {lp.key: lp.value for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}
    if P_KEYS not in live:
        raise MeterMapError(
            "this charger does not publish a custom Modbus register map "
            "(property 2570_0)"
        )
    keys = _numbers(live.get(P_KEYS))
    registers = _numbers(live.get(P_REGISTERS))
    types = _numbers(live.get(P_DATA_TYPES))
    scales = _numbers(live.get(P_SCALES))
    entries = [
        Entry(
            measurand=_name(MEASURANDS, key),
            register=registers[i] if i < len(registers) else 0,
            data_type=_name(DATA_TYPES, types[i] if i < len(types) else 0),
            scale=_signed(scales[i]) if i < len(scales) else 0,
        )
        for i, key in enumerate(keys)
        if key != UNUSED_SLOT
    ]
    return RegisterMap(entries=entries, capacity=len(keys))


def parse_json(text: str) -> RegisterMap:
    """Read one of Alfen's published register-map files."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MeterMapError(f"not a register-map file: {exc}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("Regmap"), list):
        raise MeterMapError("not a register-map file: no 'Regmap' list")
    entries = []
    for raw in doc["Regmap"]:
        if not isinstance(raw, dict):
            raise MeterMapError("a 'Regmap' entry is not an object")
        try:
            entry = Entry(
                measurand=str(raw["Key"]),
                register=int(raw["RegNum"]),
                data_type=str(raw["DataType"]),
                scale=int(raw["ScaleE"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MeterMapError(f"a 'Regmap' entry is malformed: {exc}") from None
        if entry.measurand not in MEASURANDS:
            raise MeterMapError(f"unknown measurand '{entry.measurand}'")
        if entry.data_type not in DATA_TYPES:
            raise MeterMapError(f"unknown data type '{entry.data_type}'")
        if not 0 <= entry.register <= MAX_REGISTER:
            raise MeterMapError(f"register {entry.register} is out of range")
        entries.append(entry)
    if not entries:
        raise MeterMapError("the register map is empty")
    return RegisterMap(entries=entries, name=str(doc.get("Name") or ""))


def to_json(regmap: RegisterMap, name: str = "") -> str:
    """Render a map in the format Alfen's own preset files use."""
    doc = {
        "Name": name or regmap.name,
        "Regmap": [
            {
                "Key": e.measurand,
                "RegNum": e.register,
                "DataType": e.data_type,
                "ScaleE": e.scale,
            }
            for e in regmap.entries
        ],
    }
    return json.dumps(doc, indent=2)


def apply(charger: AlfenCharger, regmap: RegisterMap, *, capacity: int) -> None:
    """Write a map to the charger, with the app's own bracketing.

    ``capacity`` is how many positions the charger's arrays hold, from a
    previous :func:`read`; the rest are padded out as unused.
    """
    if len(regmap.entries) > capacity:
        raise MeterMapError(
            f"the map has {len(regmap.entries)} entries but the charger holds "
            f"{capacity}"
        )
    keys, registers, types, scales = [], [], [], []
    for entry in regmap.entries:
        keys.append(MEASURANDS.index(entry.measurand))
        registers.append(entry.register)
        types.append(DATA_TYPES.index(entry.data_type))
        scales.append(entry.scale % BYTE_RANGE)  # two's complement, as a byte
    while len(keys) < capacity:
        keys.append(UNUSED_SLOT)
        registers.append(0)
        types.append(0)
        scales.append(0)

    live = {
        lp.key: lp.value
        for lp in charger.fetch_properties_by_ids(
            [P_LOAD_BALANCING, P_MODBUS_BALANCE_MODE]
        )
    }
    try:
        previous_mode = int(live[P_LOAD_BALANCING])
    except (KeyError, TypeError, ValueError):
        previous_mode = LOAD_BALANCING_BOTH  # what the app restores unconditionally

    if P_MODBUS_BALANCE_MODE in live:
        charger.write_properties(
            {P_MODBUS_BALANCE_MODE: (BALANCE_MODE_SOCKET, UNSIGNED8)}
        )
    charger.write_properties({P_LOAD_BALANCING: (LOAD_BALANCING_OFF, UNSIGNED8)})
    try:
        charger.write_properties(
            {
                P_KEYS: (bytes(keys), BYTEARRAY),
                P_REGISTERS: (registers, ARRAY_16),
                P_DATA_TYPES: (bytes(types), BYTEARRAY),
                P_SCALES: (bytes(scales), BYTEARRAY),
            }
        )
    finally:
        # Always put load balancing back, even if a write failed part-way:
        # leaving it off would silently stop the charger balancing at all.
        charger.write_properties({P_LOAD_BALANCING: (previous_mode, UNSIGNED8)})
