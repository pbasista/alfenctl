"""Merging live charger properties with the EDS catalog, and value typing.

The charger reports a property's runtime state (value, type code, access,
length, category); the EDS catalog adds names, titles, units and enumerated
options.  This module joins the two views into :class:`Property` and does
the user-facing value work: validating/coercing input against the property's
type (strictly -- the app silently coerces garbage to 0) and formatting
values for display.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from alfenctl.charger import (
    ACCESS_READ_ONLY,
    LiveProperty,
    encode_property_value,
)
from alfenctl.eds import (
    ARRAY_16,
    BOOLEAN,
    BYTEARRAY,
    INTEGER16,
    INTEGER32,
    INTEGER64,
    INTEGER8,
    Option,
    PropertyDef,
    REAL32,
    REAL64,
    TYPE_NAMES,
    UNSIGNED16,
    UNSIGNED32,
    UNSIGNED64,
    UNSIGNED8,
    VISIBLE_STRING,
    type_name,
)
from alfenctl import glossary
from alfenctl.errors import AlfenError

# (type code) -> (inclusive) numeric range, for strict input validation.
_INT_RANGES: dict[int, tuple[int, int]] = {
    INTEGER8: (-(2**7), 2**7 - 1),
    INTEGER16: (-(2**15), 2**15 - 1),
    INTEGER32: (-(2**31), 2**31 - 1),
    INTEGER64: (-(2**63), 2**63 - 1),
    UNSIGNED8: (0, 2**8 - 1),
    UNSIGNED16: (0, 2**16 - 1),
    UNSIGNED32: (0, 2**32 - 1),
    UNSIGNED64: (0, 2**64 - 1),
}

_REAL_TYPES = frozenset({REAL32, REAL64})
_STRING_TYPES = frozenset({VISIBLE_STRING, 9 + 1, 11, 15, 10})  # str/ustr/domain/octet
_TRUE_WORDS = frozenset({"true", "1", "yes", "on"})
_FALSE_WORDS = frozenset({"false", "0", "no", "off"})

# Longest value shown in the human table (full values always in --json).
TABLE_VALUE_MAX = 48


# --- Device-bound properties -------------------------------------------------------------

# Properties that are writable but belong to *this* charger, so copying them
# from one device's backup into another (or back after the network moved)
# would do damage: identity and serial numbers, the MAC, the clock, the IP
# configuration, the SCN membership, the SIM pin, the license key, and the
# energy-meter/Modbus wiring that describes the hardware actually installed.
#
# This is the app's own list (``PropertyStorage.s_forbiddenProperties``),
# which it applies when *writing* a settings file -- it never puts them in
# the file at all.  We keep them in an export, because a dump doubles as a
# record of what a charger was set to, and refuse them on import instead,
# where the damage would happen.  ``--force`` overrides.
NON_PORTABLE_IDS = frozenset(
    {
        0x204F,  # (unnamed; on the app's list)
        0x2051,  # sysChargePointSerialNumber
        0x2052,  # sysBoardSerial (Ethernet MAC)
        0x2053,  # sysChargeBoxIdentity
        0x2055,  # sysChargePointVendor
        0x2059,  # sysDateTime
        0x205F,  # (unnamed; on the app's list)
        0x2075,  # commIPaddress
        0x207D,  # commIPaddress2
        0x2103,  # gprsSIMpin
        0x2165,  # (unnamed; on the app's list)
        0x2166,
        0x2167,
        0x2180,  # SCN_NetworkName (Smart Charging Network membership)
        0x2187,  # (unnamed; on the app's list)
        0x21A1,  # license key
        0x2218,  # sensEnergyMeterModbusType
        0x2219,
        0x2522,  # modbus TCP/IP slave configuration
        0x2523,
        0x2530,  # OD_modbusTCPIPSlave:options
        0x2560,  # modbus smart-meter configuration
        0x2561,
        0x2562,
        0x2563,
        0x2564,
        0x2565,
        0x2570,
        0x2571,
        0x2572,
        0x2573,
        0x2574,  # modbusSmartMeterConfig:wordOrder
        0x2575,  # modbusSmartMeterUart:baudrate
        0x3218,  # sensEnergyMeterModbusType2
        0x4217,  # sensEnergyMeterType3
        0x4218,  # sensEnergyMeterModbusType3
        0x5217,
        0x5218,  # sensEnergyMeterModbusType4
    }
)


def is_portable(key: tuple[int, int]) -> bool:
    """Report whether ``key`` may be copied between chargers.

    ``key`` is ``(prop id, sub id)``; the list is keyed on the property id,
    so every sub-index of a device-bound property is device-bound too.
    """
    return key[0] not in NON_PORTABLE_IDS


# Written, accepted, and then quietly ignored until the station restarts.  The
# charger answers 200 to all of these and goes on behaving as before, which is
# the whole of "I changed it and nothing happened".  This is My Eve's own list
# (``propertiesWhenChangedNeedCSReboot``, decompiled.js:732311), and unlike the
# forbidden list above it is keyed on the exact sub-index: 0x2180_1 is the SCN
# network name, while the rest of 0x2180 is not on it.
REBOOT_REQUIRED_KEYS = frozenset(
    {
        (0x2053, 0),  # sysChargeBoxIdentity
        (0x2071, 1),  # backoffice URL, wired
        (0x2078, 1),  # backoffice URL, mobile
        (0x2081, 0),  # commProtocolName ("ocpp/json")
        (0x2082, 0),  # commProtocolVersion
        (0x2100, 0),  # gprsAPNname
        (0x2113, 0),  # gprsNetworkSelection (automatic/manual)
        (0x2114, 0),  # gprsNetworkPreference (2G/4G)
        (0x2117, 0),  # proxyEnable
        (0x2126, 0),  # authorization mode
        (0x2180, 1),  # SCN_NetworkName
        (0x2400, 1),  # master tag mode
        (0x21A1, 0),  # license key
    }
)


def needs_reboot(key: tuple[int, int]) -> bool:
    """Report whether writing ``key`` only takes effect after a restart."""
    return key in REBOOT_REQUIRED_KEYS


def reboot_required(keys: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return the keys among ``keys`` that will not take effect until a reboot."""
    return [key for key in keys if needs_reboot(key)]


@dataclass
class Property:
    """A property with its live value and (when known) its EDS definition."""

    key: tuple[int, int]
    live: LiveProperty | None
    definition: PropertyDef | None

    @property
    def id_str(self) -> str:
        """The charger-style id, e.g. ``"2062_0"``."""
        if self.live is not None:
            return self.live.id
        if self.definition is not None:
            return self.definition.id_str
        return f"{self.key[0]:X}_{self.key[1]:X}"

    @property
    def name(self) -> str:
        """The EDS parameter name, or the id when the catalog doesn't know it."""
        return self.definition.name if self.definition else self.id_str

    @property
    def title(self) -> str:
        """What the property is: the EDS title, else this program's glossary.

        The vendor's catalog describes under a third of what a charger
        answers with; :mod:`alfenctl.glossary` holds the rest, mined from
        the vendor's own apps.  ``""`` means neither has a word for it,
        which is what :attr:`known` reports.
        """
        if self.definition is not None and self.definition.title:
            return self.definition.title
        return glossary.title(self.key)

    @property
    def known(self) -> bool:
        """Whether anything describes this property (see :attr:`title`)."""
        return bool(self.title) or self.definition is not None

    @property
    def value(self) -> Any:
        """The live value (None when the charger didn't report one)."""
        return self.live.value if self.live else None

    @property
    def data_type(self) -> int | None:
        """The SDT type code: live metadata first, EDS as fallback."""
        if self.live is not None and self.live.data_type is not None:
            return self.live.data_type
        return self.definition.data_type if self.definition else None

    @property
    def type_name(self) -> str:
        """Short type name for display (``"?"`` when unknown)."""
        return type_name(self.data_type)

    @property
    def writable(self) -> bool:
        """Whether writing is allowed.

        The live ``access`` field is authoritative (1 == read-only); without
        a live reply we fall back to the EDS access mode.
        """
        if self.live is not None and self.live.access is not None:
            return self.live.access != ACCESS_READ_ONLY
        return self.definition.writable if self.definition else True

    @property
    def access_label(self) -> str:
        """``"rw"`` or ``"ro"`` for tables."""
        return "rw" if self.writable else "ro"

    @property
    def length(self) -> int | None:
        """Max length: the live ``len`` field first, EDS Length as fallback."""
        if self.live is not None and self.live.length is not None:
            return self.live.length
        return self.definition.length if self.definition else None

    @property
    def category(self) -> str:
        """The live category, when reported."""
        return (self.live.category or "") if self.live else ""

    @property
    def unit(self) -> str:
        """The EDS unit, when given."""
        return self.definition.unit if self.definition else ""

    @property
    def options(self) -> tuple[Option, ...]:
        """The EDS enumerated options, when given."""
        return self.definition.options if self.definition else ()

    def encoded(self, value: Any) -> Any:
        """Encode a typed value for this property's type (protocol form)."""
        return encode_property_value(self.data_type, value)


def as_int(value: object) -> int | None:
    """Return a value the charger reported as an int, or None.

    Property values arrive from JSON as ``object``: a number, a numeric
    string, or nothing at all when the charger does not have the property.
    """
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def merge(live: LiveProperty | None, definition: PropertyDef | None) -> Property:
    """Join a live reply with a catalog definition (either may be None).

    Not both, though: a property with neither a live value nor a catalog
    entry has no id to be known by, and callers drop those before they get
    here.
    """
    if live is not None:
        key = live.key
    elif definition is not None:
        key = (definition.prop_id, definition.sub_id)
    else:
        raise ValueError("a property needs a live reply or a catalog entry")
    return Property(key=key, live=live, definition=definition)


class PropertyValueError(AlfenError, ValueError):
    """A user-input validation error carrying the property for context."""

    def __init__(self, prop: Property, message: str) -> None:
        """Format the error against ``prop``'s id and type."""
        super().__init__(f"{prop.id_str} ({prop.type_name}): {message}")


def _resolve_option(prop: Property, raw: str) -> str:
    """Substitute an option's stored value when the input matches its title."""
    lowered = raw.strip().lower()
    for opt in prop.options:
        if opt.title and opt.title.lower() == lowered:
            return opt.value
    return raw


def coerce_input(prop: Property, raw: Any) -> Any:
    """Validate and coerce user input to the property's typed value.

    Accepts strings (from the command line) or already-typed JSON values
    (from an imported dump).  Raises :class:`PropertyValueError` with a clear
    message on any mismatch -- unlike the app, which silently coerces bad
    input to 0.
    """
    data_type = prop.data_type
    if isinstance(raw, str):
        raw = _resolve_option(prop, raw)

    if data_type is None:  # unknown type: pass through, the charger validates
        return raw

    if data_type == BOOLEAN:
        if isinstance(raw, bool):
            return raw
        word = str(raw).strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
        raise PropertyValueError(prop, f"'{raw}' is not a boolean (true/false)")

    if data_type in _REAL_TYPES:
        try:
            return float(str(raw).strip().replace(",", "."))
        except ValueError:
            raise PropertyValueError(prop, f"'{raw}' is not a number") from None

    if data_type in _INT_RANGES:
        lo, hi = _INT_RANGES[data_type]
        text = str(raw).strip()
        if isinstance(raw, str) and text.lower() in _TRUE_WORDS | _FALSE_WORDS:
            text = "1" if text.lower() in _TRUE_WORDS else "0"
        try:
            number = int(text)
        except ValueError:
            raise PropertyValueError(prop, f"'{raw}' is not an integer") from None
        if not lo <= number <= hi:
            raise PropertyValueError(prop, f"{number} out of range [{lo}, {hi}]")
        return number

    if data_type == BYTEARRAY:
        text = str(raw).replace(",", "").replace(" ", "").strip()
        if text and len(text) % 2 == 0:
            try:
                return bytes.fromhex(text)
            except ValueError:
                pass
        raise PropertyValueError(prop, f"'{raw}' is not a hex byte string (e.g. 0A,FF)")

    if data_type == ARRAY_16:
        try:
            return [int(part, 16) for part in str(raw).split(",") if part.strip()]
        except ValueError:
            raise PropertyValueError(
                prop, f"'{raw}' is not a hex u16 list (e.g. 00FF,1A00)"
            )

    if data_type in _STRING_TYPES:
        text = str(raw)
        if prop.length is not None and len(text) > prop.length:
            raise PropertyValueError(
                prop, f"value is {len(text)} chars, max {prop.length}"
            )
        return text

    return raw  # exotic type: pass through, the charger validates


# --- what the vendor app will not let you type -------------------------------------------
#
# My Eve validates 211 writable properties before it sends them; 64 of those
# rules carry a bound (research/android/android-findings.md, "validation
# rules" table, recovered from the app's Hermes bundle).  The EDS describes
# none of it, so until now `set` had only the SDT type to go on: 40 A into
# a socket maximum is a perfectly good REAL32 and a perfectly bad current.
#
# These are *warnings*, not refusals, and deliberately so.  My Eve is the
# consumer app and its bounds are the ordinary ones -- it caps a socket at
# 32 A, which is right until a station is licensed for high-power sockets and
# 40 A is exactly what was meant.  `set` is the escape hatch for everything
# the curated commands will not do, so it says what the vendor app thinks and
# then does as it is told.
#
# For NUMERIC the pair bounds the value; for STRING and HEXADECIMAL it bounds
# the length, which is how the app's own form rules read them.
NUMERIC = "numeric"
STRING = "string"
HEXADECIMAL = "hexadecimal"

VENDOR_RANGES: dict[tuple[int, int], tuple[float, float, str]] = {
    (0x205C, 0x1): (-90, 90, NUMERIC),
    (0x205C, 0x2): (-180, 180, NUMERIC),
    (0x205F, 0x0): (0, 8, NUMERIC),
    (0x2061, 0x1): (0, 8, NUMERIC),
    (0x2061, 0x2): (0, 100, NUMERIC),
    (0x2062, 0x0): (1, 64, NUMERIC),
    (0x2063, 0x0): (8, 20, STRING),
    (0x2067, 0x0): (10, 5000, NUMERIC),
    (0x2068, 0x0): (6, 100, NUMERIC),
    (0x206A, 0x0): (1, 100, NUMERIC),
    (0x206C, 0x1): (0, 5, NUMERIC),
    (0x206E, 0x0): (-720, 780, NUMERIC),
    (0x2071, 0x1): (0, 63, STRING),
    (0x2071, 0x2): (0, 63, STRING),
    (0x2076, 0x0): (0, 49, STRING),
    (0x2078, 0x1): (0, 63, STRING),
    (0x2078, 0x2): (0, 63, STRING),
    (0x2081, 0x0): (0, 20, STRING),
    (0x2100, 0x0): (0, 31, STRING),
    (0x2101, 0x0): (0, 31, STRING),
    (0x2102, 0x0): (0, 31, STRING),
    (0x2103, 0x0): (0, 21, STRING),
    (0x2106, 0x0): (0, 128, STRING),
    (0x2107, 0x0): (1, 128, NUMERIC),
    (0x2115, 0x0): (0, 63, STRING),
    (0x2116, 0x0): (0, 31, STRING),
    (0x2128, 0x0): (0, 32, NUMERIC),
    (0x2129, 0x0): (6, 32, NUMERIC),
    (0x2130, 0x0): (0, 32, NUMERIC),
    (0x2131, 0x0): (0, 128, NUMERIC),
    (0x2153, 0x0): (6, 8, NUMERIC),
    (0x2169, 0x0): (0, 3600, NUMERIC),
    (0x216D, 0x0): (0, 59, NUMERIC),
    (0x2172, 0x0): (0, 100, NUMERIC),
    (0x2173, 0x0): (1, 16, NUMERIC),
    (0x2174, 0x0): (0, 5000, NUMERIC),
    (0x2177, 0x0): (0, 223, STRING),
    (0x2178, 0x0): (0, 223, STRING),
    (0x2180, 0x1): (4, 7, STRING),
    (0x2180, 0x4): (900, 36000, NUMERIC),
    (0x2180, 0x5): (1, 5000, NUMERIC),
    (0x2180, 0x6): (6, 32, NUMERIC),
    (0x2180, 0xA): (1, 5000, NUMERIC),
    (0x2183, 0x0): (0, 2, NUMERIC),
    (0x2189, 0x0): (1, 3, NUMERIC),
    (0x2191, 0x3): (0, 65535, NUMERIC),
    (0x21A1, 0x0): (0, 30, STRING),
    (0x21B9, 0x0): (0, 3600, NUMERIC),
    (0x2202, 0x0): (-255, 255, NUMERIC),
    (0x2216, 0x0): (0, 3600, NUMERIC),
    (0x2400, 0x2): (8, 20, HEXADECIMAL),
    (0x2401, 0x0): (8, 36, HEXADECIMAL),
    (0x2571, 0x0): (1, 49, STRING),
    (0x2572, 0x0): (1, 49, STRING),
    (0x2573, 0x0): (1, 49, STRING),
    (0x2574, 0x0): (0, 1, NUMERIC),
    (0x2574, 0x3): (1, 16, NUMERIC),
    (0x2575, 0x1): (0, 2, NUMERIC),
    (0x2722, 0x0): (0, 49, STRING),
    (0x2723, 0x0): (0, 3, NUMERIC),
    (0x2911, 0x0): (0, 12, NUMERIC),
    (0x3129, 0x0): (6, 32, NUMERIC),
    (0x3173, 0x0): (1, 16, NUMERIC),
    (0x3262, 0x7): (0, 31, STRING),
}


def range_warning(key: tuple[int, int], value: Any) -> str | None:
    """Return what the vendor app would object to about ``value``, if anything."""
    rule = VENDOR_RANGES.get(key)
    if rule is None or value is None or isinstance(value, bool):
        return None
    low, high, kind = rule
    if kind == NUMERIC:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if low <= number <= high:
            return None
        return f"the vendor app keeps this between {low:g} and {high:g}"
    length = len(str(value))
    if low <= length <= high:
        return None
    unit = "hex characters" if kind == HEXADECIMAL else "characters"
    return f"the vendor app keeps this between {low:g} and {high:g} {unit}"


def format_value(prop: Property, max_chars: int | None = TABLE_VALUE_MAX) -> str:
    """Render the live value for the human-readable table."""
    value = prop.value
    if value is None:
        return ""
    if isinstance(value, list):
        text = ",".join(str(v) for v in value)
    elif isinstance(value, bytes):
        text = ",".join(f"{b:02X}" for b in value)
    else:
        text = str(value)
    if max_chars is not None and len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def values_equal(prop: Property, typed_value: Any) -> bool:
    """Compare a typed candidate with the live value in encoded form."""
    return prop.encoded(typed_value) == prop.encoded(prop.value)


__all__ = [
    "Property",
    "PropertyValueError",
    "TABLE_VALUE_MAX",
    "as_int",
    "coerce_input",
    "format_value",
    "merge",
    "type_name",
    "TYPE_NAMES",
    "values_equal",
]
