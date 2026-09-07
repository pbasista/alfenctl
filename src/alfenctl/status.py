"""A live view of what the charger is doing right now.

The app's *Monitoring* panel reads the ``states``, ``meter1`` and ``temp``
property categories and renders them as socket state, meter readings and
temperature; this module does the same for the terminal.  Everything here
is reachable with ``alfenctl get`` -- what this adds is knowing *which*
properties matter and what their numbers mean.

Per-socket state lives at ``(0x2501, n)`` for socket 1 and ``(0x2502, n)``
for socket 2 (``PanelMonitoring``): sub-index 1 is the main state
(``EMainStates``), 2 the LED state (``ELEDStates``), 3 the power/relay
state (``ESocketStates``) and 4 the Mode-3 pilot state (``EMode3States``).

Those four say what the state machine is doing.  What the charger is telling
the *person* in front of it is a second block, ``(0x3190, n)`` and
``(0x3191, n)``, which both vendor front ends read and this one did not:
sub 1 is the screen's state (``EUserInterfaceStates``) and sub 2 the error
number behind it (``EUserInterfaceError``), rendered together the way the
app renders them -- ``401: inside temperature high``.  Sub 2 is only read
while sub 1 is the error state, because the register keeps the last error's
number long after the error has gone.

``0x205F`` is the third thing a socket can be: out of service.  It is a bit
field rather than an enum -- bit 0 the whole station, bit 1 socket 1, bit 2
socket 2, a set bit meaning *in*operative -- which is worth saying because
one of the three sources this program was written from models it as a plain
two-value setting and gets a dual-socket station wrong.

**The meter block, and where the EDS is wrong about it.**  ``0x2221``
(``sensEnergyMeterValues``) is one measurand per sub-index, in the order of
``EnergyMeterMeasurand`` (see :mod:`alfenctl.meter_map`) offset by three:
voltages at 3-8, currents at 9-13, cos phi at 14-17, frequency at 18,
active power L1-L3 at 19-21 and the total at **22**, and the lifetime energy
totals at 34 (delivered) and 38 (consumed).  That is the app's own table
(``PanelMonitoring.AddNetQuality``), and a live NG910 agrees with it: its
``2221_12`` (sub 18) reads 50.11, which is a mains frequency and not the
cos phi the offset would otherwise put there.

The bundled ``EDS.xml`` disagrees at exactly two entries -- it labels sub
0x10 "Frequency" and sub 0x11 "ActivePower", which are the cos phi slots.
Active power was read from ``0x11`` here until that was noticed, which meant
the live kW was a power factor.

The EDS puts the two energy totals in the right place but gets their unit
wrong as well: it says kWh, and a real NG910 answers a thousand times the
figure its own transactions are measured in.  The register is watt-hours --
which is the unit Alfen's Modbus map uses for the same measurand -- so this
module divides, and :class:`Status` carries kWh like everything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from alfenctl.charger import AlfenCharger
from alfenctl.errors import AlfenError

# Per-socket state blocks, socket 1 and 2 (PanelMonitoring uses 9473/9474).
SOCKET_STATE_IDS = (0x2501, 0x2502)
SUB_MAIN_STATE = 1
SUB_LED_STATE = 2
SUB_POWER_STATE = 3
SUB_MODE3_STATE = 4

# The user-facing state block, socket 1 and 2 (PanelMonitoring's 12688/12689).
# Sub 1 is what the charger's own screen is showing (EUserInterfaceStates) and
# sub 2 is the error behind it -- read only when sub 1 says UI_STATE_ERROR,
# exactly as PanelMonitoring.SetStatusMessages does, because the register keeps
# the last error's number after the error itself has cleared.
DEVICE_STATE_IDS = (0x3190, 0x3191)
SUB_DEVICE_STATE = 1
SUB_DEVICE_ERROR = 2
UI_STATE_ERROR = 16

# 0x205F is a bit field, not an enum: bit 0 is the whole station, and one bit
# per socket above it (My Eve reads the same three flags; PanelMonitoring
# writes them to take a socket out of service).  A set bit means *in*operative.
P_SOCKET_FLAGS = (0x205F, 0)
STATION_INOPERATIVE_BIT = 0x1


def socket_inoperative_bit(number: int) -> int:
    """Return the 0x205F bit that takes socket ``number`` out of service."""
    return 1 << number


# Station current limits, temperature, and the energy meter's live values.
P_MAX_STATION_CURRENT = (0x2062, 0)
P_MAX_INSTALLATION_CURRENT = (0x2067, 0)
P_ACTIVE_SAFE_CURRENT = (0x2068, 0)
P_LOAD_BALANCING_MODE = (0x2064, 0)
P_TEMPERATURE = (0x2201, 0)
P_TEMPERATURE_ALARM_LOW = (0x2202, 0)
P_TEMPERATURE_ALARM_HIGH = (0x2203, 0)
METER_ID = 0x2221
SUB_VOLTAGE_L1 = 0x3
SUB_CURRENT_L1 = 0xA
SUB_POWER_L1 = 0x13  # sub 19-21, "Active Power L1/L2/L3", watts
SUB_ACTIVE_POWER = 0x16  # sub 22, "Active Power Total"; see the note above
SUB_ENERGY_DELIVERED = 0x22  # sub 34, EnergyRealDeliveredSum, Wh
SUB_ENERGY_CONSUMED = 0x26  # sub 38, EnergyRealConsumedSum, Wh
PHASES = 3
WH_PER_KWH = 1000.0  # what the energy registers count in; see the note above

# What the category walk does not carry.  A 7.4.5 NG910 answers for
# ``2221_3`` through ``2221_20`` in ``meter1`` and stops there, so the two
# lifetime totals have to be asked for by id -- the way the licence,
# hardware and SCN blocks are.  The socket flags and the two device-state
# blocks are asked for the same way: a charger that does not publish them
# simply answers for neither, and the fields stay None.
EXTRA_IDS = (
    (METER_ID, SUB_ENERGY_DELIVERED),
    (METER_ID, SUB_ENERGY_CONSUMED),
    P_SOCKET_FLAGS,
    *(
        (block, sub)
        for block in DEVICE_STATE_IDS
        for sub in (SUB_DEVICE_STATE, SUB_DEVICE_ERROR)
    ),
)

# Categories that carry the above (the app's UpdateCategories call).
STATUS_CATEGORIES = ("states", "meter1", "temp", "generic")

# EMainStates
MAIN_STATES = {
    -1: "illegal",
    0: "unknown",
    1: "booting",
    2: "available",
    3: "cable connected",
    4: "cable connected timeout",
    5: "ev connected",
    6: "button activated",
    7: "nfc available",
    8: "nfc authorised",
    9: "wait for evconnect",
    10: "charging test relays",
    11: "charging power off",
    12: "charging power off low maxcurrent",
    13: "charging power starting",
    14: "charging power on",
    15: "charging power on simplified",
    16: "charging wait for ev reconnect",
    17: "charging terminating",
    18: "charging wakeup",
    19: "wait for disconnect",
    20: "wait for release authorisation",
    21: "charging recover from outage",
    22: "error",
    23: "error message",
    24: "error message cable not supported",
    25: "error illegal mode 3",
    26: "error too many restarts",
    27: "error charging",
    28: "error charging overcurrent",
    29: "error charging hf contactor switching",
    30: "error s2 not opened",
    31: "error protective earth",
    32: "error relays",
    33: "error low supply voltage",
    34: "error internal voltage",
    35: "error powermeter",
    36: "error temperature",
    37: "suspended",
    38: "inoperative",
    39: "reserved",
    40: "error charging rcd signaled",
    41: "charging power off ventilating",
    42: "charging power off suspended",
    43: "charging power off phase change",
    44: "wait for start metervalue",
    45: "wait for stop metervalue",
    46: "error socket motor",
    47: "cable connected type e",
    48: "cable connected timeout type e",
    49: "charging type e",
    50: "wait for disconnect type e",
    51: "charging suspended type e",
    52: "charging low maxcurrent type e",
    53: "invalid card",
    54: "ev connected unauthorized",
    55: "wait for disconnect pp",
}
# ELEDStates
LED_STATES = {
    0: "unknown",
    1: "off",
    2: "booting",
    3: "booting check mains",
    4: "available",
    5: "prep authorizing",
    6: "prep authorized",
    7: "prep cable connected",
    8: "prep ev connected",
    9: "charging preparing",
    10: "charging wait vehicle",
    11: "charging active normal",
    12: "charging active simplified",
    13: "charging suspended overcurrent",
    14: "charging suspended hf switching",
    15: "charging suspended ev disconnected",
    16: "finish wait vehicle",
    17: "finish wait for disconnect",
    18: "error protective earth",
    19: "error powerline fault",
    20: "error contactor fault",
    21: "error charging",
    22: "error powerfailure",
    23: "error temperature",
    24: "error illegal cp value",
    25: "error illegal pp value",
    26: "error",
    27: "error too many restarts",
    28: "errormessage",
    29: "errormessage not authorized",
    30: "errormessage cable not supported",
    31: "errormessage s2 not opened",
    32: "errormessage timeout",
    33: "reserved",
    34: "inoperative",
    35: "loadbalancing limited",
    36: "loadbalancing forced off",
    37: "tag mode",
    38: "tag mode added",
    39: "tag mode removed",
    40: "charging non charging",
}
# ESocketStates (the relay configuration behind the socket)
POWER_STATES = {
    -1: "unknown",
    0: "main off, bypass off",
    1: "main on, bypass off",
    2: "main on, bypass on",
    3: "main on, triac on",
}
# EMode3States: the IEC 61851 control-pilot state, and what it means.
MODE3_STATES = {
    160: "A (no vehicle)",
    161: "A1 (no vehicle)",
    162: "A2 (no vehicle)",
    177: "B1 (vehicle connected, not ready)",
    178: "B2 (vehicle connected, ready)",
    193: "C1 (charging, no ventilation)",
    194: "C2 (charging)",
    209: "D1 (charging, ventilation required)",
    210: "D2 (charging, ventilation)",
    224: "E (error: no power)",
    240: "F (error: unavailable)",
}


# EUserInterfaceStates: what the charger is telling the person in front of it.
DEVICE_STATES = {
    0: "unknown",
    1: "booting",
    2: "available",
    3: "cable connected",
    4: "vehicle connected",
    5: "cable authorised",
    6: "authorised",
    7: "communicating",
    8: "off (current limit too low)",
    9: "off (suspended)",
    10: "charging",
    11: "charged (locked)",
    12: "charged (unlocked)",
    13: "waiting for the vehicle to reconnect",
    14: "transaction info",
    15: "card rejected",
    16: "error",
    17: "please wait",
    18: "reserved",
    19: "QR code",
    20: "warning",
    21: "waiting for release",
    22: "please remove the cable",
    23: "please wait (talking to the vehicle)",
    24: "waiting for release",
    25: "invalid card",
}

# EUserInterfaceError, with the words and the severity the app's Monitoring
# panel puts on each (PanelMonitoring.TDisplayStatesMessagesNew).  A few codes
# carry no message there at all: the app treats them as nothing to report, so
# they are "info" here and say only what they are.
DEVICE_ERRORS: dict[int, tuple[str, str]] = {
    0: ("info", "installation OK"),
    1: ("warning", "not able to charge -- call for support"),
    101: ("warning", "one moment please, the session will resume shortly"),
    102: ("error", "not able to charge -- call for support"),
    104: ("error", "not able to charge -- call for support"),
    105: ("error", "not able to charge -- call for support"),
    106: ("error", "not able to charge -- call for support"),
    107: ("error", "not able to lock the cable -- call for support"),
    108: ("info", "missing charge point id"),
    109: ("info", "NFC reader"),
    201: ("error", "error in installation -- check it or call for support"),
    202: ("error", "input voltage too low -- call your installer"),
    206: ("warning", "temporarily unavailable -- contact the operator"),
    208: ("info", "supply voltage too high"),
    209: ("info", "P1 port"),
    210: ("info", "Modbus TCP/IP port"),
    211: ("error", "not able to lock the cable -- call for support"),
    212: ("error", "error in installation -- check it or call for support"),
    213: ("error", "TIC port"),
    301: ("warning", "one moment please, the session will resume shortly"),
    302: ("warning", "one moment please, the session will resume shortly"),
    303: ("warning", "charging not started -- reconnect the cable"),
    304: ("warning", "charging not started -- reconnect the cable"),
    401: ("warning", "inside temperature high -- charging will resume shortly"),
    402: ("warning", "inside temperature low -- charging will resume shortly"),
    403: ("warning", "charging not started -- reconnect the cable"),
    404: ("warning", "not able to lock the cable -- reconnect it"),
    405: ("warning", "cable not supported -- try connecting it again"),
    406: ("warning", "no communication with the vehicle -- check the cable"),
    407: ("info", "tilt"),
}


@dataclass
class SocketStatus:
    """What one socket is doing."""

    number: int
    main_state: str | None = None
    led_state: str | None = None
    power_state: str | None = None
    mode3_state: str | None = None
    device_state: str | None = None
    """What the charger's own screen is saying, when it reports it."""

    error_code: int | None = None
    """The error behind ``device_state``, set only while the socket is in one."""

    error_text: str | None = None
    error_severity: str | None = None
    """``info``, ``warning`` or ``error`` -- the app's own icon for the code."""

    operative: bool | None = None
    """False when 0x205F has this socket's bit set; None when it says nothing."""

    @property
    def present(self) -> bool:
        """Whether the charger reported anything at all for this socket."""
        return any(
            (
                self.main_state,
                self.led_state,
                self.power_state,
                self.mode3_state,
                self.device_state,
            )
        )

    @property
    def error(self) -> str | None:
        """The error as the app writes it, e.g. ``401: inside temperature high``."""
        if self.error_code is None or self.error_text is None:
            return None
        return f"{self.error_code:03d}: {self.error_text}"


@dataclass
class Status:
    """A snapshot of the charger's live state."""

    sockets: list[SocketStatus] = field(default_factory=list)
    station_operative: bool | None = None
    """False when 0x205F bit 0 is set -- the whole station is out of service."""

    temperature_c: float | None = None
    temperature_alarm: tuple[float | None, float | None] = (None, None)
    max_station_current_a: float | None = None
    max_installation_current_a: float | None = None
    active_safe_current_a: float | None = None
    voltages_v: list[float] = field(default_factory=list)
    currents_a: list[float] = field(default_factory=list)
    powers_w: list[float] = field(default_factory=list)
    """Active power per phase, as the meter reports it.

    Read rather than worked out.  Volts times amps is apparent power, and
    the difference between that and this is the power factor -- a car
    charging at 16 A on 230 V is not necessarily taking 3.68 kW, and on
    three phases the three numbers would not add up to the total beside
    them.  The meter already has the answer (``2221_13`` through
    ``2221_15``, beside the total this reads from ``2221_16``).
    """

    active_power_w: float | None = None
    energy_delivered_kwh: float | None = None
    """Lifetime energy the meter has delivered -- what the cars took."""

    energy_consumed_kwh: float | None = None
    """Lifetime energy measured the other way -- out of the car, into the grid.

    A station that cannot do that reports zero here for its whole life, which
    is why the terminal and the dashboard leave the line out until it is not.
    """


def _number(values: dict[tuple[int, int], Any], key: tuple[int, int]) -> float | None:
    """Read a property as a float, or None when it is absent or not numeric."""
    raw = values.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _kwh(values: dict[tuple[int, int], Any], key: tuple[int, int]) -> float | None:
    """Read a lifetime energy register, whose counting unit is watt-hours."""
    total = _number(values, key)
    return None if total is None else total / WH_PER_KWH


def _code(values: dict[tuple[int, int], Any], key: tuple[int, int]) -> int | None:
    """Read a property as an integer state code."""
    number = _number(values, key)
    return None if number is None else int(number)


def _label(table: dict[int, str], code: int | None) -> str | None:
    """Look up a state code, keeping the raw number when the table lacks it."""
    if code is None:
        return None
    return table.get(code, f"unknown ({code})")


def _read_device_state(
    values: dict[tuple[int, int], Any], block: int, socket: SocketStatus
) -> None:
    """Fill in what the charger's own screen says, and the error behind it.

    The error register keeps the last error's number after the error has
    cleared, so it is only meaningful while the state itself is the error one
    -- which is the test the app's Monitoring panel makes before reading it.
    """
    state = _code(values, (block, SUB_DEVICE_STATE))
    if state is None:
        return
    socket.device_state = _label(DEVICE_STATES, state)
    if state != UI_STATE_ERROR:
        return
    code = _code(values, (block, SUB_DEVICE_ERROR))
    if code is None:
        return
    socket.error_code = code
    severity, text = DEVICE_ERRORS.get(
        code, ("warning", "unknown error or warning state -- call for support")
    )
    socket.error_severity, socket.error_text = severity, text


def read(values: dict[tuple[int, int], Any], sockets: int = 1) -> Status:
    """Build a :class:`Status` from a property map, skipping what is absent."""
    status = Status()
    flags = _code(values, P_SOCKET_FLAGS)
    if flags is not None:
        status.station_operative = not flags & STATION_INOPERATIVE_BIT
    for index in range(min(sockets or 1, len(SOCKET_STATE_IDS))):
        block = SOCKET_STATE_IDS[index]
        number = index + 1
        socket = SocketStatus(
            number=number,
            main_state=_label(MAIN_STATES, _code(values, (block, SUB_MAIN_STATE))),
            led_state=_label(LED_STATES, _code(values, (block, SUB_LED_STATE))),
            power_state=_label(POWER_STATES, _code(values, (block, SUB_POWER_STATE))),
            mode3_state=_label(MODE3_STATES, _code(values, (block, SUB_MODE3_STATE))),
        )
        if flags is not None:
            socket.operative = not flags & socket_inoperative_bit(number)
        _read_device_state(values, DEVICE_STATE_IDS[index], socket)
        if socket.present:
            status.sockets.append(socket)
    status.temperature_c = _number(values, P_TEMPERATURE)
    status.temperature_alarm = (
        _number(values, P_TEMPERATURE_ALARM_LOW),
        _number(values, P_TEMPERATURE_ALARM_HIGH),
    )
    status.max_station_current_a = _number(values, P_MAX_STATION_CURRENT)
    status.max_installation_current_a = _number(values, P_MAX_INSTALLATION_CURRENT)
    status.active_safe_current_a = _number(values, P_ACTIVE_SAFE_CURRENT)
    status.voltages_v = [
        v
        for i in range(PHASES)
        if (v := _number(values, (METER_ID, SUB_VOLTAGE_L1 + i))) is not None
    ]
    status.currents_a = [
        v
        for i in range(PHASES)
        if (v := _number(values, (METER_ID, SUB_CURRENT_L1 + i))) is not None
    ]
    status.powers_w = [
        v
        for i in range(PHASES)
        if (v := _number(values, (METER_ID, SUB_POWER_L1 + i))) is not None
    ]
    status.active_power_w = _number(values, (METER_ID, SUB_ACTIVE_POWER))
    status.energy_delivered_kwh = _kwh(values, (METER_ID, SUB_ENERGY_DELIVERED))
    status.energy_consumed_kwh = _kwh(values, (METER_ID, SUB_ENERGY_CONSUMED))
    return status


def collect(charger: AlfenCharger, sockets: int = 1) -> Status:
    """Read one live snapshot from a charger: the walk, plus what it misses.

    Both front ends want the same reading and used to build it separately,
    which is how one of them could quietly be a register behind the other.
    The category walk is most of it; :data:`EXTRA_IDS` is the rest, and a
    charger that will not answer for those simply reports no total.
    """
    values: dict[tuple[int, int], Any] = {}
    for category in STATUS_CATEGORIES:
        try:
            values.update(
                {lp.key: lp.value for lp in charger.fetch_properties(category)}
            )
        except httpx.HTTPError:
            continue  # a category this firmware does not publish
    try:
        values.update(
            {
                lp.key: lp.value
                for lp in charger.fetch_properties_by_ids(list(EXTRA_IDS))
            }
        )
    except (httpx.HTTPError, AlfenError):
        pass  # no lifetime totals on this firmware; the rest of it still reads
    return read(values, sockets)


def render(status: Status) -> list[str]:
    """Render a status snapshot as report lines (empty sections dropped)."""
    lines: list[str] = []
    if status.station_operative is False:
        lines.append(f"  {'Station':<12} out of service")
        lines.append("")
    for socket in status.sockets:
        label = f"Socket {socket.number}"
        head = socket.main_state or "unknown"
        if socket.operative is False:
            head += "  (out of service)"
        lines.append(f"  {label:<12} {head}")
        for name, value in (
            ("Display", socket.device_state),
            ("Mode 3", socket.mode3_state),
            ("LED", socket.led_state),
            ("Power", socket.power_state),
        ):
            if value:
                lines.append(f"  {'':<12} {name}: {value}")
        if socket.error:
            lines.append(
                f"  {'':<12} {socket.error_severity or 'error'}: {socket.error}"
            )
    limits = [
        (name, value)
        for name, value in (
            ("station", status.max_station_current_a),
            ("installation", status.max_installation_current_a),
            ("safe", status.active_safe_current_a),
        )
        if value is not None
    ]
    if limits:
        lines.append("")
        lines.append(
            f"  {'Limits':<12} "
            + ", ".join(f"{value:g} A {name}" for name, value in limits)
        )
    # Delivered is what the cars took, and a charger fresh from its box
    # honestly has none of it.  Consumed is the other direction, which stays
    # at zero unless the station can send power back, so a zero there says
    # nothing and gets no line.
    energy: list[tuple[str, float]] = []
    if status.energy_delivered_kwh is not None:
        energy.append(("Delivered", status.energy_delivered_kwh))
    if status.energy_consumed_kwh:
        energy.append(("Consumed", status.energy_consumed_kwh))
    if (
        status.voltages_v
        or status.currents_a
        or status.powers_w
        or status.active_power_w is not None
        or energy
    ):
        lines.append("")
        if status.voltages_v:
            lines.append(
                f"  {'Voltage':<12} "
                + " / ".join(f"{v:.1f}" for v in status.voltages_v)
                + " V"
            )
        if status.currents_a:
            lines.append(
                f"  {'Current':<12} "
                + " / ".join(f"{v:.1f}" for v in status.currents_a)
                + " A"
            )
        if status.powers_w:
            lines.append(
                f"  {'Power/phase':<12} "
                + " / ".join(f"{v / 1000:.2f}" for v in status.powers_w)
                + " kW"
            )
        if status.active_power_w is not None:
            lines.append(f"  {'Power':<12} {status.active_power_w / 1000:.2f} kW")
        # The meter's own lifetime totals, which is what a charging session
        # is measured against.
        for label, total in energy:
            lines.append(f"  {label:<12} {total:.3f} kWh")
    if status.temperature_c is not None:
        low, high = status.temperature_alarm
        alarm = (
            f"  (alarm below {low:g} or above {high:g})"
            if None not in (low, high)
            else ""
        )
        lines.append("")
        lines.append(f"  {'Temperature':<12} {status.temperature_c:.1f} C{alarm}")
    return lines
