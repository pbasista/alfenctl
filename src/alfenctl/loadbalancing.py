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

from devicectl import fields
from devicectl.fields import FieldSpec

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


def _mode_row(_value: Any, state: LoadBalancing) -> str:
    """Render the two mode bits the way the app's two checkboxes read together."""
    return state.mode_label


def _p1_row(value: Any, state: LoadBalancing) -> str | None:
    """Render the P1 interface with the server it points at, when there is one."""
    if value is None:
        return None
    where = P1_INTERFACES.get(int(value), f"unknown ({value})")
    if state.p1_address:
        where += f" ({state.p1_address}:{state.p1_port})"
    return where


# --- the settings ------------------------------------------------------------------------
# One row per setting, in the order the terminal prints them, and the single
# place any of the five audiences is told about a field: :func:`read` decodes
# by walking it, :meth:`LoadBalancing.rows` prints by walking it,
# ``web.schema`` serialises by walking it, ``cli.commands.loadbalancing`` adds
# its flags by walking it, and :func:`apply` writes by walking it.
#
# Three of them are not in the table's own shape.  The mode is a bit field, so
# it is read here and written through ``static``/``active``, which have no
# register of their own; the P1 server's address and port are read-only and
# print inside the interface's row rather than beside it; and the solar boost
# is one register per socket, which is a dict, not a field.
FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        name="mode_raw",
        kind=fields.INTEGER,
        address=P_MODE,
        label="Mode",
        json="modeRaw",
        access=fields.READ_ONLY,
        render=_mode_row,
    ),
    FieldSpec(
        name="static",
        kind=fields.FLAG,
        json="static",
        flag="--static",
        help="static load balancing",
    ),
    FieldSpec(
        name="active",
        kind=fields.FLAG,
        json="active",
        flag="--active",
        help="active load balancing",
    ),
    FieldSpec(
        name="protocol",
        kind=fields.ENUM,
        address=P_PROTOCOL,
        wire=INTEGER8,
        label="Meter protocol",
        json="protocol",
        flag="--protocol",
        options=PROTOCOLS,
        what="the meter protocol",
        help="smart meter protocol",
    ),
    FieldSpec(
        name="data_source",
        kind=fields.ENUM,
        address=P_DATA_SOURCE,
        wire=INTEGER8,
        label="Data source",
        json="dataSource",
        flag="--data-source",
        options=DATA_SOURCES,
        what="the data source",
        help="what active balancing follows",
    ),
    FieldSpec(
        name="max_meter_current_a",
        kind=fields.NUMBER,
        address=P_MAX_METER_CURRENT,
        wire=REAL32,
        label="Max meter current",
        json="maxMeterCurrentA",
        flag="--max-meter-current",
        unit="A",
        minimum=MIN_METER_CURRENT_A,
        maximum=MAX_METER_CURRENT_A,
        metavar="AMPS",
        what="the maximum meter current",
        help="the grid connection's limit",
    ),
    FieldSpec(
        name="safe_current_a",
        kind=fields.NUMBER,
        address=P_SAFE_CURRENT,
        wire=REAL32,
        label="Safe current",
        json="safeCurrentA",
        flag="--safe-current",
        unit="A",
        minimum=MIN_SAFE_CURRENT_A,
        maximum=MAX_SAFE_CURRENT_A,
        metavar="AMPS",
        what="the safe current",
        help="what to fall back to when the meter stops answering",
    ),
    FieldSpec(
        name="max_imbalance_a",
        kind=fields.NUMBER,
        address=P_MAX_IMBALANCE,
        wire=REAL32,
        label="Max imbalance",
        json="maxImbalanceA",
        flag="--max-imbalance",
        unit="A",
        minimum=0.0,
        maximum=MAX_METER_CURRENT_A,
        metavar="AMPS",
        what="the maximum imbalance",
        help="allowed imbalance between phases",
    ),
    FieldSpec(
        name="measurement_includes_ev",
        kind=fields.ENUM,
        address=P_MEASUREMENT_INCLUDES_EV,
        wire=INTEGER8,
        label="Measurement",
        json="measurementIncludesEv",
        flag="--includes-ev",
        options=MEASUREMENT_SOURCES,
        aliases=fields.ON_OFF_CODES,
        what="the measurement source",
        help="whether the meter's reading already counts the charging car",
    ),
    FieldSpec(
        name="phase_rotation",
        kind=fields.TEXT,
        address=P_PHASE_ROTATION,
        wire=VISIBLE_STRING,
        label="Phase rotation",
        json="phaseRotation",
        flag="--phase-rotation",
        options=PHASE_ROTATIONS,
        what="the phase rotation",
        help="how the phases are wired to this station",
    ),
    FieldSpec(
        name="max_allowed_phases",
        kind=fields.INTEGER,
        address=P_MAX_ALLOWED_PHASES,
        wire=UNSIGNED32,
        label="Max allowed phases",
        json="maxAllowedPhases",
        flag="--max-phases",
        options=ALLOWED_PHASES,
        what="the maximum allowed phases",
        help="the most phases a session may use",
    ),
    FieldSpec(
        name="phase_switching",
        kind=fields.FLAG,
        address=P_PHASE_SWITCHING,
        wire=INTEGER8,
        label="Phase switching",
        json="phaseSwitching",
        flag="--phase-switching",
        words=("on", "off"),
        help="allow 1-/3-phase switching",
    ),
    FieldSpec(
        name="p1_interface",
        kind=fields.ENUM,
        address=P_P1_INTERFACE,
        label="P1 interface",
        json="p1Interface",
        options=P1_INTERFACES,
        access=fields.READ_ONLY,
        render=_p1_row,
    ),
    FieldSpec(
        name="p1_address",
        kind=fields.TEXT,
        address=P_P1_ADDRESS,
        json="p1Address",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="p1_port",
        kind=fields.INTEGER,
        address=P_P1_PORT,
        json="p1Port",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="solar_mode",
        kind=fields.ENUM,
        address=P_SOLAR_MODE,
        wire=INTEGER8,
        label="Solar charging",
        json="solarMode",
        flag="--solar-mode",
        options=SOLAR_MODES,
        what="the solar mode",
        help="solar charging",
    ),
    FieldSpec(
        name="solar_green_share",
        kind=fields.INTEGER,
        address=P_SOLAR_GREEN_SHARE,
        wire=UNSIGNED16,
        label="  green share",
        json="solarGreenShare",
        flag="--green-share",
        unit="%",
        minimum=MIN_GREEN_SHARE,
        maximum=MAX_GREEN_SHARE,
        metavar="PERCENT",
        what="the green share",
        help="surplus share to charge from",
    ),
    FieldSpec(
        name="solar_comfort_w",
        kind=fields.INTEGER,
        address=P_SOLAR_COMFORT_LEVEL,
        wire=UNSIGNED32,
        label="  comfort level",
        json="solarComfortW",
        flag="--comfort-level",
        unit="W",
        minimum=MIN_COMFORT_W,
        maximum=MAX_COMFORT_W,
        metavar="WATTS",
        what="the comfort level",
        help="the floor comfort mode keeps",
    ),
)

# Every register one round trip has to ask for: the table's, plus the two
# per-socket boost flags that are a dict rather than a field.
ALL_KEYS = (
    *(spec.address for spec in FIELDS if spec.address is not None),
    *SOLAR_BOOST.values(),
)


class LoadBalancingError(AlfenError, fields.FieldError):
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
        out = fields.rows(FIELDS, self)
        for number, on in sorted(self.solar_boost.items()):
            out.append((f"  boost socket {number}", "on" if on else "off"))
        return out


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

    live: dict[tuple[int, int], LiveProperty] = {
        lp.key: lp for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))
    }

    def answer(key: tuple[int, int]) -> Any:
        prop = live.get(key)
        return None if prop is None else prop.value

    state = LoadBalancing(**fields.harvest(FIELDS, answer))
    for number, key in SOLAR_BOOST.items():
        boost = answer(key)
        if boost is not None:
            state.solar_boost[number] = bool(int(float(boost)))
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
    settings: dict[str, Any] | None = None,
    *,
    state: LoadBalancing | None = None,
    **named: Any,
) -> LoadBalancing:
    """Write the settings that were named, and return the charger's new state.

    Settings arrive either as a mapping -- which is what a command line and a
    request body turn into, neither of them having to name the fields a second
    time -- or as keywords, which is how the rest of this program calls it.

    Three of them are not plain field writes.  ``static`` and ``active`` share
    one register, so setting either is a read-modify-write of the other's bit;
    ``state`` is the reading the caller already has, and is taken fresh when it
    was not supplied.  ``solar_boost`` maps a socket number to a flag.
    """
    given = {**(settings or {}), **named}
    boost = given.pop("solar_boost", None)
    try:
        checked = fields.values(FIELDS, given)
        static = checked.pop("static", None)
        active = checked.pop("active", None)
        writes = fields.writes(FIELDS, checked)
    except fields.FieldError as exc:
        raise LoadBalancingError(str(exc)) from None
    if static is not None or active is not None:
        if state is None:
            state = read(charger)
        raw = state.mode_raw or 0
        for flag, bit in ((static, STATIC_BIT), (active, ACTIVE_BIT)):
            if flag is not None:
                raw = (raw | bit) if flag else (raw & ~bit)
        writes[P_MODE] = (raw, INTEGER8)
    for number, on in (boost or {}).items():
        key = SOLAR_BOOST.get(int(number))
        if key is None:
            raise LoadBalancingError(f"there is no socket {number} on an Alfen station")
        writes[key] = (int(bool(on)), INTEGER8)
    if writes:
        charger.write_properties(writes)
    return read(charger)


__all__ = [
    "ALL_KEYS",
    "DATA_SOURCES",
    "FIELDS",
    "LoadBalancing",
    "LoadBalancingError",
    "PHASE_ROTATIONS",
    "PROTOCOLS",
    "SOLAR_MODES",
    "apply",
    "read",
]
