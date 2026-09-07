"""The settings people change often: current limits and display brightness.

Everything here is reachable with ``alfenctl get``/``set`` already.  What
this module adds is the part the app knows and a property id does not: which
handful of ids matter, what their numbers mean together, and which
combinations the charger will accept but not honour.

**Current limits.** The app's *Power* panel (``PanelPower``) writes three
numbers.  ``sysMaxStationCurrent`` (0x2062, "Station maximum current") is
what the supply to the whole station can carry.  ``mainNormalMaxCurrent``
(0x2129 for socket 1, 0x3129 for socket 2 -- the app's 8489 and 12585) is
what one socket may draw.  ``sysMaxInstallationCurrent`` (0x2067) is the
building's limit, which the app only exposes below firmware 4.1 and which is
read-only here.

Two rules come from the app rather than from the charger, which accepts the
writes either way:

* a socket maximum above the station maximum is pointless -- the station
  limit wins, and the app shows "the max current(s) cannot be higher than
  the maximum station current" (``PanelPower.UpdateWarnings``);
* the *sum* of the socket maxima above the station maximum is only
  meaningful with static load balancing or a Smart Charging Network; the app
  quietly rewrites both sockets to half the station current when it sees it
  (``MainWindow.ValidateCSConfiguration``).

Both are reported as warnings, not refusals: a station that really is load
balanced is entitled to the second configuration, and we are not in a
position to know which it is.

**Temperature alarms.** ``sensTemperatureAlarmLow`` (0x2202) and
``sensTemperatureAlarmHigh`` (0x2203) are the band the charger's own
temperature has to stay inside; outside it the station raises an alarm and
one of its main states is "error temperature".  The app edits them in its
*Alerts* panel (``PanelAlerts``), and the EDS makes both ``rw`` REAL32 with
defaults of -25 and 70 C.  They are read here with the other settings so the
dashboard can show the live reading against the band it has to stay in.

**Brightness.** ``sysIntensity`` (0x2061) holds the LED and display
brightness as a percentage in sub-index 2, and the auto-dim setting in
sub-index 1.  Newer firmware makes that second one a bit field (the app
reads its length: bit 0 auto-dim, bit 1 by time, bit 2 by inactivity, bit 4
for QR codes) where older firmware has a plain flag.  Bit 0 means the same
thing in both, so it is the bit this module flips -- keeping the rest of the
field as it found it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from alfenctl import status
from alfenctl.charger import AlfenCharger, LiveProperty
from alfenctl.eds import INTEGER8, REAL32, UNSIGNED32
from alfenctl.errors import AlfenError

P_STATION_MAX_CURRENT = (0x2062, 0)  # 8290 sysMaxStationCurrent, amps
P_INSTALLATION_MAX_CURRENT = (0x2067, 0)  # 8295 sysMaxInstallationCurrent, amps
# 8489 and 12585 in the app: mainNormalMaxCurrent for socket 1 and socket 2.
SOCKET_MAX_CURRENT = {1: (0x2129, 0), 2: (0x3129, 0)}
P_INTENSITY_AUTO = (0x2061, 1)  # 8289 sub 1, auto-dim (a flag or a bit field)
P_INTENSITY = (0x2061, 2)  # 8289 sub 2, LED/display intensity, percent
P_NR_SOCKETS = (0x205E, 0)  # 8286 how many sockets this station actually has

# The live half of the current limits, one block per socket.  ``EXTERNAL`` is
# the RAM register an external controller drives -- a solar or dynamic-tariff
# script writes here rather than at the socket maximum, because this one is
# not stored and a reboot returns the station to its configured limit.  The
# other three are read-only: what static balancing, active balancing and the
# P1 meter are each allowing right now, which is how you tell a limit that was
# configured from the limit actually in force.
SOCKET_EXTERNAL_MAX = {1: (0x212A, 0), 2: (0x312A, 0)}  # 8490 / 12586
SOCKET_STATIC_LB_MAX = {1: (0x212B, 0), 2: (0x312B, 0)}  # 8491 / 12587, ro
SOCKET_ACTIVE_MAX = {1: (0x212C, 0), 2: (0x312C, 0)}  # 8492 / 12588, ro
SOCKET_P1_MAX = {1: (0x212D, 0), 2: (0x312D, 0)}  # 8493 / 12589, ro
P_TEMPERATURE_ALARM_LOW = (0x2202, 0)  # 8706 sensTemperatureAlarmLow, C
P_TEMPERATURE_ALARM_HIGH = (0x2203, 0)  # 8707 sensTemperatureAlarmHigh, C

ALL_KEYS = (
    P_STATION_MAX_CURRENT,
    P_INSTALLATION_MAX_CURRENT,
    *SOCKET_MAX_CURRENT.values(),
    P_INTENSITY_AUTO,
    P_INTENSITY,
    P_NR_SOCKETS,
    P_TEMPERATURE_ALARM_LOW,
    P_TEMPERATURE_ALARM_HIGH,
    *SOCKET_EXTERNAL_MAX.values(),
    *SOCKET_STATIC_LB_MAX.values(),
    *SOCKET_ACTIVE_MAX.values(),
    *SOCKET_P1_MAX.values(),
)

# The bit that means "dim by yourself" in both shapes of 0x2061 sub 1.
AUTO_DIM_BIT = 0x1

# A charger takes any number here; these are the bounds the app's own dialog
# allows.  1 A is its floor for every model, and 64 A its ceiling (a twin or
# a station on more than one feeder cable); an ordinary single-feeder station
# stops at 32 A, which is a warning rather than a refusal because the model
# details that decide it are not all readable.
MIN_CURRENT_A = 1.0
MAX_CURRENT_A = 64.0
ORDINARY_MAX_CURRENT_A = 32.0

# The lowest limit a car can actually charge at.  Mode 3 encodes the offered
# current in the pilot's duty cycle, and IEC 61851-1 defines nothing below
# 6 A: a vehicle that sees less is required not to draw current at all.  The
# charger agrees -- one of its own main states is "charging power off low
# maxcurrent" (see :mod:`alfenctl.status`) -- so a limit under this is not a
# slow charge, it is no charge.
#
# The charger still *accepts* anything from :data:`MIN_CURRENT_A` up, and a
# commissioning engineer has reasons to write such a value, so this is not
# enforced by :func:`check_current`.  It is the floor the UI's sliders offer
# and what a value below it is measured against.
MIN_CHARGE_CURRENT_A = 6.0

MIN_INTENSITY = 0
MAX_INTENSITY = 100

# The ends of the alarm sliders.  The charger takes whatever it is sent;
# this is the range an outdoor cabinet lives in, wide enough that the
# vendor's own defaults (-25 and 70 C) sit well inside it.  A station
# already set outside it is still shown where it is -- the UI opens its
# track to whatever the charger holds -- exactly as the currents are.
MIN_ALARM_TEMPERATURE_C = -40.0
MAX_ALARM_TEMPERATURE_C = 100.0


class ControlError(AlfenError, ValueError):
    """A value that would not mean anything on the charger."""


@dataclass(frozen=True)
class Caveat:
    """Something set that will not have the effect it looks like it has.

    Two audiences read the same finding: a terminal, which has room for the
    whole of it, and a dashboard card, which has a line.  So each one is
    written twice -- ``short`` names the problem, ``detail`` explains it --
    rather than letting the UI truncate a sentence at a word boundary.
    """

    short: str
    detail: str

    def __str__(self) -> str:
        """Render as the long form, which is what a terminal wants."""
        return self.detail


@dataclass
class Controls:
    """The current limits and brightness a charger reports."""

    station_max_a: float | None = None
    installation_max_a: float | None = None
    sockets: dict[int, float] = field(default_factory=dict)
    """Per-socket maximum current, keyed by socket number."""

    socket_count: int | None = None
    """How many sockets the station reports having (None: it did not say)."""

    intensity: int | None = None
    auto_dim: bool | None = None
    auto_dim_raw: int | None = None
    """The whole of 0x2061 sub 1, so a write keeps the bits we do not set."""

    temp_alarm_low_c: float | None = None
    temp_alarm_high_c: float | None = None
    """The band the charger's own temperature has to stay inside."""

    external_max_a: dict[int, float] = field(default_factory=dict)
    """What an external controller has asked for, per socket (0x212A/0x312A)."""

    effective_a: dict[int, dict[str, float]] = field(default_factory=dict)
    """Per socket, what each balancing source is allowing right now."""

    def warnings(self) -> list[Caveat]:
        """Return what is set but will not have the effect it looks like."""
        out: list[Caveat] = []
        if self.station_max_a is None:
            return out
        ceiling = self.station_max_a
        if self.installation_max_a is not None:
            ceiling = min(ceiling, self.installation_max_a)
        for number, amps in sorted(self.sockets.items()):
            if amps > ceiling:
                out.append(
                    Caveat(
                        f"socket {number} is above the station limit",
                        f"socket {number} is set to {amps:g} A, above the "
                        f"{ceiling:g} A the station allows; the lower one wins",
                    )
                )
        for number, amps in sorted(self.sockets.items()):
            if amps < MIN_CHARGE_CURRENT_A:
                out.append(
                    Caveat(
                        f"socket {number} is below the charging minimum",
                        f"socket {number} is set to {amps:g} A, under the "
                        f"{MIN_CHARGE_CURRENT_A:g} A floor Mode 3 can offer a "
                        "car; the socket will not charge at all, not slowly",
                    )
                )
        if len(self.sockets) > 1 and sum(self.sockets.values()) > self.station_max_a:
            total = sum(self.sockets.values())
            out.append(
                Caveat(
                    "the sockets add up past the station maximum",
                    f"the sockets add up to {total:g} A against a station "
                    f"maximum of {self.station_max_a:g} A, which only works "
                    "with static load balancing or a Smart Charging Network",
                )
            )
        return out


def _number(live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]):
    """Return one live property's value as a float, or None if absent."""
    prop = live.get(key)
    if prop is None or prop.value is None or prop.value == "":
        return None
    try:
        return float(prop.value)
    except (TypeError, ValueError):
        return None


def read(charger: AlfenCharger) -> Controls:
    """Read the limits and brightness in one ``ids=`` query.

    Both socket ids are asked for regardless of how many sockets the station
    has, and so is the socket count, because *answering* for socket 2 does
    not mean having one.  A single-socket NG910 builds the whole object
    dictionary its firmware knows -- its own boot log says ``Added object
    0x3129`` -- and returns 16 A for a socket that is not on the wall.
    Taking that at face value put a phantom socket on the dashboard and
    raised the "sockets add up past the station maximum" warning against a
    station with one.  So the reply is trimmed to the sockets
    ``sysNrOfSockets`` says exist; a charger too old to report it keeps the
    old behaviour of believing what it answered.
    """
    live = {lp.key: lp for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}
    count = _number(live, P_NR_SOCKETS)
    limit = int(count) if count is not None and count >= 1 else len(SOCKET_MAX_CURRENT)
    sockets: dict[int, float] = {}
    for number, key in SOCKET_MAX_CURRENT.items():
        amps = _number(live, key)
        if amps is not None and number <= limit:
            sockets[number] = amps
    external: dict[int, float] = {}
    for number, key in SOCKET_EXTERNAL_MAX.items():
        amps = _number(live, key)
        if amps is not None and number <= limit:
            external[number] = amps
    effective: dict[int, dict[str, float]] = {}
    for number in sockets:
        allowing = {
            name: amps
            for name, table in (
                ("static", SOCKET_STATIC_LB_MAX),
                ("active", SOCKET_ACTIVE_MAX),
                ("P1", SOCKET_P1_MAX),
            )
            if (amps := _number(live, table[number])) is not None
        }
        if allowing:
            effective[number] = allowing
    auto_raw = _number(live, P_INTENSITY_AUTO)
    intensity = _number(live, P_INTENSITY)
    return Controls(
        external_max_a=external,
        effective_a=effective,
        station_max_a=_number(live, P_STATION_MAX_CURRENT),
        installation_max_a=_number(live, P_INSTALLATION_MAX_CURRENT),
        sockets=sockets,
        socket_count=None if count is None else int(count),
        intensity=None if intensity is None else int(intensity),
        auto_dim=None if auto_raw is None else bool(int(auto_raw) & AUTO_DIM_BIT),
        auto_dim_raw=None if auto_raw is None else int(auto_raw),
        temp_alarm_low_c=_number(live, P_TEMPERATURE_ALARM_LOW),
        temp_alarm_high_c=_number(live, P_TEMPERATURE_ALARM_HIGH),
    )


def check_current(amps: float, what: str = "current") -> float:
    """Return ``amps`` if a charger could sensibly be set to it."""
    if math.isnan(amps) or amps < MIN_CURRENT_A or amps > MAX_CURRENT_A:
        raise ControlError(
            f"{what} must be between {MIN_CURRENT_A:g} and {MAX_CURRENT_A:g} A"
        )
    return float(amps)


def check_temperature(degrees: float, what: str = "temperature") -> float:
    """Return ``degrees`` if it is an alarm limit worth setting."""
    if (
        math.isnan(degrees)
        or degrees < MIN_ALARM_TEMPERATURE_C
        or degrees > MAX_ALARM_TEMPERATURE_C
    ):
        raise ControlError(
            f"{what} must be between {MIN_ALARM_TEMPERATURE_C:g} and "
            f"{MAX_ALARM_TEMPERATURE_C:g} C"
        )
    return float(degrees)


def check_intensity(percent: int) -> int:
    """Return ``percent`` if it is a brightness the charger accepts."""
    if percent < MIN_INTENSITY or percent > MAX_INTENSITY:
        raise ControlError(
            f"brightness must be between {MIN_INTENSITY} and {MAX_INTENSITY}%"
        )
    return int(percent)


def apply(
    charger: AlfenCharger,
    *,
    station_max_a: float | None = None,
    sockets: dict[int, float] | None = None,
    external_sockets: dict[int, float] | None = None,
    intensity: int | None = None,
    auto_dim: bool | None = None,
    temp_alarm_low: float | None = None,
    temp_alarm_high: float | None = None,
    state: Controls | None = None,
) -> Controls:
    """Write the settings that were named, and return the charger's new state.

    Everything goes in one ``POST /api/prop`` batch, so a page that changes
    the station limit and both sockets at once holds the charger for a single
    round trip.  ``state`` is the reading the caller already has; it is only
    needed to preserve the auto-dim field's other bits, and is re-read if it
    was not supplied.
    """
    writes: dict[tuple[int, int], tuple[Any, int | None]] = {}
    if station_max_a is not None:
        writes[P_STATION_MAX_CURRENT] = (
            check_current(station_max_a, "the station maximum"),
            REAL32,
        )
    for number, amps in (sockets or {}).items():
        key = SOCKET_MAX_CURRENT.get(number)
        if key is None:
            raise ControlError(f"there is no socket {number} on an Alfen station")
        writes[key] = (check_current(amps, f"socket {number}"), REAL32)
    for number, amps in (external_sockets or {}).items():
        # The external request is not stored: it is what a solar or tariff
        # controller is asking for at this moment, and the charger forgets it
        # on the next boot.  Same range as a socket maximum, different life.
        key = SOCKET_EXTERNAL_MAX.get(number)
        if key is None:
            raise ControlError(f"there is no socket {number} on an Alfen station")
        writes[key] = (check_current(amps, f"socket {number}"), REAL32)
    if temp_alarm_low is not None or temp_alarm_high is not None:
        # One end can be moved on its own, and the pair still has to make
        # sense afterwards, so the other end comes from the charger.
        if state is None:
            state = read(charger)
        low = (
            check_temperature(temp_alarm_low, "the low temperature alarm")
            if temp_alarm_low is not None
            else state.temp_alarm_low_c
        )
        high = (
            check_temperature(temp_alarm_high, "the high temperature alarm")
            if temp_alarm_high is not None
            else state.temp_alarm_high_c
        )
        if low is not None and high is not None and low >= high:
            raise ControlError(
                f"the low temperature alarm ({low:g} C) has to be below the "
                f"high one ({high:g} C)"
            )
        if temp_alarm_low is not None:
            writes[P_TEMPERATURE_ALARM_LOW] = (low, REAL32)
        if temp_alarm_high is not None:
            writes[P_TEMPERATURE_ALARM_HIGH] = (high, REAL32)
    if intensity is not None:
        writes[P_INTENSITY] = (check_intensity(intensity), INTEGER8)
    if auto_dim is not None:
        if state is None:
            state = read(charger)
        raw = state.auto_dim_raw or 0
        writes[P_INTENSITY_AUTO] = (
            (raw | AUTO_DIM_BIT) if auto_dim else (raw & ~AUTO_DIM_BIT),
            INTEGER8,
        )
    if not writes:
        raise ControlError("nothing to set")
    charger.write_properties(writes)
    return read(charger)


def format_current(state: Controls) -> list[tuple[str, str]]:
    """Render the current limits as label/value rows."""
    rows = [
        (
            "Station maximum",
            "<not reported>"
            if state.station_max_a is None
            else f"{state.station_max_a:g} A",
        )
    ]
    if state.installation_max_a is not None:
        rows.append(("Installation maximum", f"{state.installation_max_a:g} A"))
    for number, amps in sorted(state.sockets.items()):
        rows.append((f"Socket {number} maximum", f"{amps:g} A"))
        external = state.external_max_a.get(number)
        if external is not None:
            rows.append(("  external request", f"{external:g} A"))
        allowing = state.effective_a.get(number) or {}
        if allowing:
            rows.append(
                (
                    "  now allowing",
                    ", ".join(f"{amps:g} A {name}" for name, amps in allowing.items()),
                )
            )
    return rows


def format_brightness(state: Controls) -> list[tuple[str, str]]:
    """Render the brightness settings as label/value rows."""
    return [
        (
            "Intensity",
            "<not reported>" if state.intensity is None else f"{state.intensity}%",
        ),
        (
            "Auto dim",
            "<not reported>"
            if state.auto_dim is None
            else ("on" if state.auto_dim else "off"),
        ),
    ]


# --- taking a socket out of service -----------------------------------------------------
# 0x205F is a bit field, and its layout lives in :mod:`alfenctl.status` beside
# the rest of what a socket's state is made of.  Reading it is a report, so it
# belongs there; writing it is a change, so it is here with the other dials.

# The EDS never described 0x205F, so a write has to name a type itself.  The
# Windows app sends it as a 32-bit unsigned (research/windows/
# windows-findings.md, "TYPE HINTS" section, u32 row); the charger's own
# answer wins whenever it gives one.
SOCKET_FLAGS_TYPE = UNSIGNED32


def read_socket_flags(charger: AlfenCharger) -> tuple[int, int] | None:
    """Return the 0x205F bit field and the type to write it back as.

    None when the station does not carry the register at all, which is how
    firmware too old for it answers.
    """
    live = {
        lp.key: lp for lp in charger.fetch_properties_by_ids([status.P_SOCKET_FLAGS])
    }
    prop = live.get(status.P_SOCKET_FLAGS)
    if prop is None or prop.value is None:
        return None
    try:
        flags = int(float(prop.value))
    except (TypeError, ValueError):
        return None
    return flags, prop.data_type or SOCKET_FLAGS_TYPE


def set_socket_operative(
    charger: AlfenCharger, number: int, operative: bool, *, flags: int | None = None
) -> int:
    """Put one socket in or out of service, and return the new bit field.

    A read-modify-write, because the one register holds every socket's bit and
    the station's own: writing the whole word to disable socket 2 is how socket
    1 quietly goes out of service with it.  Pass ``flags`` when the caller has
    already read them; the type then comes from :data:`SOCKET_FLAGS_TYPE`.
    """
    if number not in SOCKET_MAX_CURRENT:
        raise ControlError(f"there is no socket {number} on an Alfen station")
    data_type = SOCKET_FLAGS_TYPE
    if flags is None:
        reading = read_socket_flags(charger)
        if reading is None:
            raise ControlError(
                "this charger does not report the socket status flags (0x205F_0), "
                "so a socket cannot be taken out of service"
            )
        flags, data_type = reading
    bit = status.socket_inoperative_bit(number)
    updated = (flags & ~bit) if operative else (flags | bit)
    if updated != flags:
        charger.write_properties({status.P_SOCKET_FLAGS: (updated, data_type)})
    return updated
