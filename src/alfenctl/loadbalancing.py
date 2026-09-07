"""Load balancing and solar charging: how a station shares a supply.

The app's *Load balancing* panel (``PanelLoadbalancing``) is the largest of
its configuration pages, and every setting on it is a plain property this
program could already write.  What it adds is the part a property id does
not carry: which registers belong together, that two of them are bit fields
rather than enumerations, and which combinations the charger will accept but
cannot act on.

**The mode is a bit field.**  ``sysLoadBalancingMode`` (0x2064) has bit 0 for
static balancing and bit 1 for active, so a station can have neither, either
or both -- the app draws them as two independent checkboxes for exactly that
reason.  Writing the whole byte to turn one on is how the other silently gets
switched off, which is what :func:`apply` avoids by reading first.

**Static** balancing divides a fixed supply between the sockets and needs no
meter.  **Active** balancing follows a live measurement and does: the meter
speaks one of four protocols (``0x5217``), and the charger keeps the total
under ``sysMaxSmartMeterCurrent`` (0x2067), falling back to
``sysActiveSafeCurrent`` (0x2068) when the measurement stops arriving.  That
fallback is the setting worth getting right: it is what the station does when
its meter dies, so a safe current above what the supply can carry is a real
hazard rather than a misconfiguration.

**Solar charging** (0x3280) is a third mode on top: *comfort* keeps charging
at a floor the house cannot supply from the roof, *green* charges only on
surplus.  The two override flags (subs 4 and 5) are per socket and mean "just
this session, charge anyway" -- My Eve calls it a boost, and it is the one
setting here that is aimed at a driver rather than an installer.

Everything is read and written in one round trip, and nothing is written that
was not named: the charger accepts a write to a load-balancing register it has
no licence for, and then ignores it, so :func:`read` reports the licence
alongside the setting and the CLI says when the two disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from alfenctl.charger import AlfenCharger, LiveProperty
from alfenctl.eds import INTEGER8, REAL32, UNSIGNED16, UNSIGNED32, VISIBLE_STRING
from alfenctl.errors import AlfenError

# --- the registers -----------------------------------------------------------------------
P_MODE = (0x2064, 0)  # 8292 sysLoadBalancingMode, a bit field
P_MAX_METER_CURRENT = (0x2067, 0)  # 8295 sysMaxSmartMeterCurrent, A
P_SAFE_CURRENT = (0x2068, 0)  # 8296 sysActiveSafeCurrent, A
P_PHASE_ROTATION = (0x2069, 0)  # 8297 sysP1PhaseConnection, a string
P_MEASUREMENT_INCLUDES_EV = (0x206F, 0)  # 8303 sysSmartMeterIncludesEV
P_MAX_IMBALANCE = (0x2174, 0)  # 8564 mainMaxImbalanceCurrent, A
P_PHASE_SWITCHING = (0x2185, 0)  # 8581 allow single-/multiphase charging
P_MAX_ALLOWED_PHASES = (0x2189, 0)  # 8585 mainMaxAllowedPhases, 1 or 3
P_DATA_SOURCE = (0x2530, 1)  # 9520 sub 1, where the measurement comes from
P_PROTOCOL = (0x5217, 0)  # 21015 smart-meter protocol selection
P_P1_INTERFACE = (0x2191, 1)  # 8593 sub 1, DSMR/SMR interface
P_P1_ADDRESS = (0x2191, 2)  # 8593 sub 2, DSMR/SMR server IP
P_P1_PORT = (0x2191, 3)  # 8593 sub 3, DSMR/SMR server port

P_SOLAR_MODE = (0x3280, 1)  # 12928 sub 1, off/comfort/green
P_SOLAR_GREEN_SHARE = (0x3280, 2)  # sub 2, percent
P_SOLAR_COMFORT_LEVEL = (0x3280, 3)  # sub 3, watts
SOLAR_BOOST = {1: (0x3280, 4), 2: (0x3280, 5)}  # subs 4 and 5, one per socket

ALL_KEYS = (
    P_MODE,
    P_MAX_METER_CURRENT,
    P_SAFE_CURRENT,
    P_PHASE_ROTATION,
    P_MEASUREMENT_INCLUDES_EV,
    P_MAX_IMBALANCE,
    P_PHASE_SWITCHING,
    P_MAX_ALLOWED_PHASES,
    P_DATA_SOURCE,
    P_PROTOCOL,
    P_P1_INTERFACE,
    P_P1_ADDRESS,
    P_P1_PORT,
    P_SOLAR_MODE,
    P_SOLAR_GREEN_SHARE,
    P_SOLAR_COMFORT_LEVEL,
    *SOLAR_BOOST.values(),
)

# ELoadBalancingMode, as two bits (the app's two checkboxes).
STATIC_BIT = 0x1
ACTIVE_BIT = 0x2

# The meter protocols the app offers (its m_dicSmartMeters); My Eve's
# CSSmartMeterProtocolSelectionType agrees on every value.
PROTOCOLS = {
    -1: "EMS",
    4: "Modbus TCP/IP",
    5: "DSMR 4.x / SMR 5.0 (P1)",
    6: "Modbus RTU",
    7: "TIC (Linky)",
}

# ETCPIPSlaveOptions: which measurement active balancing follows.
DATA_SOURCES = {0: "meter", 1: "meter and EMS", 3: "EMS"}

# P1InterfaceSettingsSelectionType.
P1_INTERFACES = {0: "serial", 1: "telnet", 2: "HomeWizard Wi-Fi P1"}

# ESolarChargingModes.
SOLAR_OFF, SOLAR_COMFORT, SOLAR_GREEN = 0, 1, 2
SOLAR_MODES = {SOLAR_OFF: "off", SOLAR_COMFORT: "comfort", SOLAR_GREEN: "green"}

# The phase rotations the charger names.  This one is a *string* register --
# it stores "L1L2L3", not an index -- which is worth stating because the same
# nine options appear as a numeric enum elsewhere in the vendor's own code.
PHASE_ROTATIONS = (
    "L1",
    "L2",
    "L3",
    "L1L2L3",
    "L1L3L2",
    "L2L1L3",
    "L2L3L1",
    "L3L1L2",
    "L3L2L1",
)

# sysSmartMeterIncludesEV: whether the meter's reading already has the car in it.
MEASUREMENT_SOURCES = {0: "excluding the charging EV", 1: "including the charging EV"}

# What the app's own dialog allows (My Eve validates the same bounds).
MIN_SAFE_CURRENT_A, MAX_SAFE_CURRENT_A = 0.0, 100.0
MIN_METER_CURRENT_A, MAX_METER_CURRENT_A = 0.0, 5000.0
MIN_GREEN_SHARE, MAX_GREEN_SHARE = 0, 100
MIN_COMFORT_W, MAX_COMFORT_W = 1350, 11000
ALLOWED_PHASES = (1, 3)


class LoadBalancingError(AlfenError, ValueError):
    """A load-balancing setting the charger could not sensibly be given."""


@dataclass
class LoadBalancing:
    """How this station shares its supply, and what it is licensed to."""

    mode_raw: int | None = None
    max_meter_current_a: float | None = None
    safe_current_a: float | None = None
    phase_rotation: str | None = None
    measurement_includes_ev: int | None = None
    max_imbalance_a: float | None = None
    phase_switching: bool | None = None
    max_allowed_phases: int | None = None
    data_source: int | None = None
    protocol: int | None = None
    p1_interface: int | None = None
    p1_address: str | None = None
    p1_port: int | None = None
    solar_mode: int | None = None
    solar_green_share: int | None = None
    solar_comfort_w: int | None = None
    solar_boost: dict[int, bool] = field(default_factory=dict)
    licensed_static: bool | None = None
    licensed_active: bool | None = None
    licensed_scn: bool | None = None

    @property
    def static(self) -> bool | None:
        """Whether static balancing is switched on."""
        return None if self.mode_raw is None else bool(self.mode_raw & STATIC_BIT)

    @property
    def active(self) -> bool | None:
        """Whether active balancing is switched on."""
        return None if self.mode_raw is None else bool(self.mode_raw & ACTIVE_BIT)

    @property
    def mode_label(self) -> str:
        """The mode in words, the way the app's two checkboxes read together."""
        if self.mode_raw is None:
            return "unknown"
        on = [n for n, f in (("static", self.static), ("active", self.active)) if f]
        return " + ".join(on) if on else "off"

    def warnings(self) -> list[str]:
        """Return what is configured but cannot take effect, in the app's own terms."""
        out: list[str] = []
        if self.static and self.licensed_static is False:
            out.append(
                "static load balancing is on, but this station is not licensed for it"
            )
        if self.active and self.licensed_active is False:
            out.append(
                "active load balancing is on, but this station is not licensed for it"
            )
        if self.active and self.protocol is None:
            out.append("active load balancing is on with no meter protocol selected")
        if self.solar_mode and not self.active:
            out.append("solar charging needs active load balancing, which is off")
        return out

    def rows(self) -> list[tuple[str, str]]:
        """Return the label/value pairs worth printing, skipping what is absent."""
        out: list[tuple[str, str]] = [("Mode", self.mode_label)]
        if self.protocol is not None:
            out.append(("Meter protocol", _label(PROTOCOLS, self.protocol)))
        if self.data_source is not None:
            out.append(("Data source", _label(DATA_SOURCES, self.data_source)))
        for label, amps in (
            ("Max meter current", self.max_meter_current_a),
            ("Safe current", self.safe_current_a),
            ("Max imbalance", self.max_imbalance_a),
        ):
            if amps is not None:
                out.append((label, f"{amps:g} A"))
        if self.measurement_includes_ev is not None:
            out.append(
                (
                    "Measurement",
                    _label(MEASUREMENT_SOURCES, self.measurement_includes_ev),
                )
            )
        if self.phase_rotation:
            out.append(("Phase rotation", self.phase_rotation))
        if self.max_allowed_phases is not None:
            out.append(("Max allowed phases", str(self.max_allowed_phases)))
        if self.phase_switching is not None:
            out.append(("Phase switching", "on" if self.phase_switching else "off"))
        if self.p1_interface is not None:
            where = _label(P1_INTERFACES, self.p1_interface)
            if self.p1_address:
                where += f" ({self.p1_address}:{self.p1_port})"
            out.append(("P1 interface", where))
        if self.solar_mode is not None:
            out.append(("Solar charging", _label(SOLAR_MODES, self.solar_mode)))
            if self.solar_green_share is not None:
                out.append(("  green share", f"{self.solar_green_share}%"))
            if self.solar_comfort_w is not None:
                out.append(("  comfort level", f"{self.solar_comfort_w} W"))
        for number, on in sorted(self.solar_boost.items()):
            out.append((f"  boost socket {number}", "on" if on else "off"))
        return out


def _label(table: dict[int, str], code: int) -> str:
    """Look up a code, keeping the raw number when the table lacks it."""
    return table.get(code, f"unknown ({code})")


def _number(
    live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]
) -> float | None:
    """Read a property as a float, or None when absent or not numeric."""
    prop = live.get(key)
    if prop is None or prop.value is None:
        return None
    try:
        return float(prop.value)
    except (TypeError, ValueError):
        return None


def _int(live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]) -> int | None:
    """Read a property as an integer, or None when absent or not numeric."""
    value = _number(live, key)
    return None if value is None else int(value)


def _text(
    live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]
) -> str | None:
    """Read a property as a non-empty string, or None."""
    prop = live.get(key)
    if prop is None or prop.value in (None, ""):
        return None
    return str(prop.value)


def read(charger: AlfenCharger) -> LoadBalancing:
    """Read every load-balancing and solar register in one ``ids=`` query.

    The licence is read too, and by id: the three licence registers belong to
    no category, and a setting that is on without the feature behind it is the
    single most common reason a charger ignores what it was told.
    """
    from alfenctl.license import (
        FEATURE_LOAD_BALANCING_ACTIVE,
        FEATURE_LOAD_BALANCING_SCN,
        FEATURE_LOAD_BALANCING_STATIC,
        feature_unlocked,
        read_license,
    )

    live = {lp.key: lp for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}
    state = LoadBalancing(
        mode_raw=_int(live, P_MODE),
        max_meter_current_a=_number(live, P_MAX_METER_CURRENT),
        safe_current_a=_number(live, P_SAFE_CURRENT),
        phase_rotation=_text(live, P_PHASE_ROTATION),
        measurement_includes_ev=_int(live, P_MEASUREMENT_INCLUDES_EV),
        max_imbalance_a=_number(live, P_MAX_IMBALANCE),
        max_allowed_phases=_int(live, P_MAX_ALLOWED_PHASES),
        data_source=_int(live, P_DATA_SOURCE),
        protocol=_int(live, P_PROTOCOL),
        p1_interface=_int(live, P_P1_INTERFACE),
        p1_address=_text(live, P_P1_ADDRESS),
        p1_port=_int(live, P_P1_PORT),
        solar_mode=_int(live, P_SOLAR_MODE),
        solar_green_share=_int(live, P_SOLAR_GREEN_SHARE),
        solar_comfort_w=_int(live, P_SOLAR_COMFORT_LEVEL),
    )
    switching = _int(live, P_PHASE_SWITCHING)
    if switching is not None:
        state.phase_switching = bool(switching)
    for number, key in SOLAR_BOOST.items():
        boost = _int(live, key)
        if boost is not None:
            state.solar_boost[number] = bool(boost)
    # Which of the three balancing features this station may actually use.
    # feature_unlocked, not a plain bit test: firmware below the licensing
    # floor has every feature and reports no bitmask at all, and calling that
    # "unlicensed" would put a warning on every old charger.
    info = charger.basic_info()
    licence = read_license(charger)
    ahp = info.family == "AHP"
    for name, bit in (
        ("licensed_static", FEATURE_LOAD_BALANCING_STATIC),
        ("licensed_active", FEATURE_LOAD_BALANCING_ACTIVE),
        ("licensed_scn", FEATURE_LOAD_BALANCING_SCN),
    ):
        setattr(
            state,
            name,
            feature_unlocked(info.firmware, licence.features_raw, bit, ahp=ahp),
        )
    return state


def check_current(amps: float, what: str, low: float, high: float) -> float:
    """Return ``amps`` if it is inside the range the app allows for it."""
    if not low <= amps <= high:
        raise LoadBalancingError(f"{what} must be between {low:g} and {high:g} A")
    return float(amps)


def apply(
    charger: AlfenCharger,
    *,
    static: bool | None = None,
    active: bool | None = None,
    protocol: int | None = None,
    data_source: int | None = None,
    max_meter_current_a: float | None = None,
    safe_current_a: float | None = None,
    max_imbalance_a: float | None = None,
    phase_rotation: str | None = None,
    measurement_includes_ev: bool | None = None,
    phase_switching: bool | None = None,
    max_allowed_phases: int | None = None,
    solar_mode: int | None = None,
    solar_green_share: int | None = None,
    solar_comfort_w: int | None = None,
    solar_boost: dict[int, bool] | None = None,
    state: LoadBalancing | None = None,
) -> LoadBalancing:
    """Write the settings that were named, and return the charger's new state.

    ``static`` and ``active`` share one register, so turning either on or off
    is a read-modify-write of the other's bit -- ``state`` is the reading the
    caller already has, and is re-read when it was not supplied.
    """
    writes: dict[tuple[int, int], tuple[Any, int | None]] = {}
    if static is not None or active is not None:
        if state is None:
            state = read(charger)
        raw = state.mode_raw or 0
        for flag, bit in ((static, STATIC_BIT), (active, ACTIVE_BIT)):
            if flag is not None:
                raw = (raw | bit) if flag else (raw & ~bit)
        writes[P_MODE] = (raw, INTEGER8)
    if protocol is not None:
        if protocol not in PROTOCOLS:
            raise LoadBalancingError(
                f"unknown meter protocol {protocol}; "
                + ", ".join(f"{v} ({n})" for v, n in sorted(PROTOCOLS.items()))
            )
        writes[P_PROTOCOL] = (protocol, INTEGER8)
    if data_source is not None:
        if data_source not in DATA_SOURCES:
            raise LoadBalancingError(f"unknown data source {data_source}")
        writes[P_DATA_SOURCE] = (data_source, INTEGER8)
    if max_meter_current_a is not None:
        writes[P_MAX_METER_CURRENT] = (
            check_current(
                max_meter_current_a,
                "the maximum meter current",
                MIN_METER_CURRENT_A,
                MAX_METER_CURRENT_A,
            ),
            REAL32,
        )
    if safe_current_a is not None:
        writes[P_SAFE_CURRENT] = (
            check_current(
                safe_current_a,
                "the safe current",
                MIN_SAFE_CURRENT_A,
                MAX_SAFE_CURRENT_A,
            ),
            REAL32,
        )
    if max_imbalance_a is not None:
        writes[P_MAX_IMBALANCE] = (
            check_current(
                max_imbalance_a, "the maximum imbalance", 0.0, MAX_METER_CURRENT_A
            ),
            REAL32,
        )
    if phase_rotation is not None:
        if phase_rotation not in PHASE_ROTATIONS:
            raise LoadBalancingError(
                f"unknown phase rotation {phase_rotation!r}; one of "
                + ", ".join(PHASE_ROTATIONS)
            )
        writes[P_PHASE_ROTATION] = (phase_rotation, VISIBLE_STRING)
    if measurement_includes_ev is not None:
        writes[P_MEASUREMENT_INCLUDES_EV] = (int(measurement_includes_ev), INTEGER8)
    if phase_switching is not None:
        writes[P_PHASE_SWITCHING] = (int(phase_switching), INTEGER8)
    if max_allowed_phases is not None:
        if max_allowed_phases not in ALLOWED_PHASES:
            raise LoadBalancingError("the maximum allowed phases is 1 or 3")
        writes[P_MAX_ALLOWED_PHASES] = (max_allowed_phases, UNSIGNED32)
    if solar_mode is not None:
        if solar_mode not in SOLAR_MODES:
            raise LoadBalancingError(
                "the solar mode is off, comfort or green (0, 1 or 2)"
            )
        writes[P_SOLAR_MODE] = (solar_mode, INTEGER8)
    if solar_green_share is not None:
        if not MIN_GREEN_SHARE <= solar_green_share <= MAX_GREEN_SHARE:
            raise LoadBalancingError(
                f"the green share is a percentage ({MIN_GREEN_SHARE}-{MAX_GREEN_SHARE})"
            )
        writes[P_SOLAR_GREEN_SHARE] = (solar_green_share, UNSIGNED16)
    if solar_comfort_w is not None:
        if not MIN_COMFORT_W <= solar_comfort_w <= MAX_COMFORT_W:
            raise LoadBalancingError(
                f"the comfort level must be between {MIN_COMFORT_W} and "
                f"{MAX_COMFORT_W} W"
            )
        writes[P_SOLAR_COMFORT_LEVEL] = (solar_comfort_w, UNSIGNED32)
    for number, on in (solar_boost or {}).items():
        key = SOLAR_BOOST.get(number)
        if key is None:
            raise LoadBalancingError(f"there is no socket {number} on an Alfen station")
        writes[key] = (int(on), INTEGER8)
    if writes:
        charger.write_properties(writes)
    return read(charger)


__all__ = [
    "ALL_KEYS",
    "DATA_SOURCES",
    "LoadBalancing",
    "LoadBalancingError",
    "PHASE_ROTATIONS",
    "PROTOCOLS",
    "SOLAR_MODES",
    "apply",
    "read",
]
