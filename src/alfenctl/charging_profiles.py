"""OCPP smart-charging profiles, and the UK Smart Charging default schedule.

``GET/POST /api/chargingprofiles`` manages OCPP 1.6 ``ChargingProfile``
objects the charger enforces locally, independent of any backoffice
(``ICUChargingProfiles``). The app's own UI only ever installs one built-in
profile through it -- the default schedule required by the UK's Electric
Vehicles (Smart Charging) Regulations 2021, which blocks charging during
peak hours on weekdays unless overridden -- identified by the fixed id
``s_idUKSmartCharging``; :func:`uk_default_profile` reproduces it exactly,
including its randomised-delay and local-time flags. Reading, listing and
clearing profiles is generic and works on any profile, not just that one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from alfenctl.charger import AlfenCharger
from alfenctl.eds import UNSIGNED8, UNSIGNED32
from alfenctl.errors import AlfenError

# ICUChargingProfiles.s_idUKSmartCharging: a fixed, recognisable profile id.
UK_SMART_CHARGING_ID = -19061964

CLEAR_ALL = "all"

# ICUChargingProfiles.GetChargingProfile only understands this reply shape.
_PROFILE_DOC_VERSION = 2

# The weekly schedule AddUkSmartChargingProfile builds: block (0 A) during
# the two weekday peak windows, allow (32 A) the rest of the time -- seconds
# from Monday 00:00 (the recurring week's startSchedule).
_PEAK_START_1 = 8 * 3600  # 08:00
_OFFPEAK_START_1 = 11 * 3600  # 11:00
_PEAK_START_2 = 16 * 3600  # 16:00
_OFFPEAK_START_2 = 22 * 3600  # 22:00
_SECONDS_PER_DAY = 86400
_WEEKDAYS = 5  # Monday..Friday get the peak/off-peak pattern
_ALLOW_A = 32
_BLOCK_A = 0


@dataclass(frozen=True)
class SchedulePeriod:
    """One ``chargingSchedulePeriod`` entry: a limit from an offset onward."""

    start_period_s: int
    limit_a: float


@dataclass(frozen=True)
class ChargingProfile:
    """One charging profile, as read back from the charger."""

    connector_id: int
    profile_id: int
    kind: str
    purpose: str
    stack_level: int
    charging_rate_unit: str
    start_schedule: str | None
    periods: list[SchedulePeriod]
    raw: dict[str, Any]

    @property
    def is_uk_default(self) -> bool:
        """Whether this is the built-in UK Smart Charging profile."""
        return self.profile_id == UK_SMART_CHARGING_ID


def parse_ids(body: str) -> list[int]:
    """Parse a ``?id_list`` reply (``{"ChargingProfileIDs": [...]}``)."""
    try:
        doc = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        return []
    entries = doc.get("ChargingProfileIDs") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        return []
    out = []
    for entry in entries:
        value = entry.get("Value") if isinstance(entry, dict) else entry
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


def parse_profiles(body: str) -> list[ChargingProfile]:
    """Parse a ``?cpid=`` reply (``ICUChargingProfiles.GetChargingProfile``, version 2)."""
    try:
        doc = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        return []
    if not isinstance(doc, dict) or doc.get("version") != _PROFILE_DOC_VERSION:
        return []
    out: list[ChargingProfile] = []
    for connector in doc.get("Profile", []):
        if not isinstance(connector, dict):
            continue
        connector_id = connector.get("connectorId", 0)
        for raw in connector.get("csChargingProfiles", []):
            if not isinstance(raw, dict):
                continue
            schedule = raw.get("chargingSchedule") or {}
            periods = [
                SchedulePeriod(
                    start_period_s=int(p.get("startPeriod", 0)),
                    limit_a=float(p.get("limit", 0)),
                )
                for p in schedule.get("chargingSchedulePeriod", [])
                if isinstance(p, dict)
            ]
            try:
                profile_id = int(raw.get("chargingProfileId"))
            except (TypeError, ValueError):
                continue
            out.append(
                ChargingProfile(
                    connector_id=int(connector_id) if connector_id else 0,
                    profile_id=profile_id,
                    kind=str(raw.get("chargingProfileKind", "")),
                    purpose=str(raw.get("chargingProfilePurpose", "")),
                    stack_level=int(raw.get("stackLevel", 0) or 0),
                    charging_rate_unit=str(schedule.get("chargingRateUnit", "")),
                    start_schedule=schedule.get("startSchedule"),
                    periods=periods,
                    raw=raw,
                )
            )
    return out


def uk_default_profile(now: datetime | None = None) -> dict[str, Any]:
    """Build the UK Smart Charging default profile (``AddUkSmartChargingProfile``).

    A recurring weekly schedule, referenced to the most recent Monday
    00:00 UTC: Monday-Friday it blocks charging 08:00-11:00 and
    16:00-22:00 and allows 32 A the rest of the time (including weekends),
    matching the peak-avoidance window the UK's Electric Vehicles (Smart
    Charging) Regulations 2021 require by default. ``useRandomisedDelay``
    adds the regulation's other requirement, a randomised start delay.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start_of_week = now.date() - timedelta(days=now.weekday())  # Monday
    start_schedule = f"{start_of_week.isoformat()}T00:00:00Z"

    periods = [{"startPeriod": 0, "limit": _ALLOW_A}]
    offset = 0
    for _ in range(_WEEKDAYS):
        periods += [
            {"startPeriod": offset + _PEAK_START_1, "limit": _BLOCK_A},
            {"startPeriod": offset + _OFFPEAK_START_1, "limit": _ALLOW_A},
            {"startPeriod": offset + _PEAK_START_2, "limit": _BLOCK_A},
            {"startPeriod": offset + _OFFPEAK_START_2, "limit": _ALLOW_A},
        ]
        offset += _SECONDS_PER_DAY

    return {
        "connectorId": 0,
        "csChargingProfiles": {
            "chargingProfileId": UK_SMART_CHARGING_ID,
            "chargingProfileKind": "Recurring",
            "recurrencyKind": "Weekly",
            "chargingProfilePurpose": "ChargingStationExternalConstraints",
            "useLocalTime": True,
            "useRandomisedDelay": True,
            "stackLevel": 1,
            "chargingSchedule": {
                "startSchedule": start_schedule,
                "chargingRateUnit": "A",
                "chargingSchedulePeriod": periods,
            },
        },
    }


# --- overriding an installed profile from the station itself -------------------------------
# A profile installed here is enforced by the charger whether or not anyone is
# watching, which is the point of the UK regulation.  It also means a driver who
# plugs in during a blocked window gets nothing, so the firmware carries a
# per-socket escape hatch: "Direct start on socket N" in the app's Charging
# profiles category (PanelLoadbalancing.cs:801-802), a property rather than a
# profile edit.  Neither register is in EDS.xml, so writes take the type the
# charger reported for them, and fall back to the app's own reading.

P_RANDOM_DELAY = (0x21B9, 0)  # 8633 chargingProfileMaxRandomDelay, seconds
SOCKET_OVERRIDE = {1: (0x3278, 1), 2: (0x3278, 2)}  # 12920 sub 1 / sub 2

OVERRIDE_FOLLOW = 0
OVERRIDE_DIRECT_START = 1
OVERRIDE_LABELS = {
    OVERRIDE_FOLLOW: "follow profile",
    OVERRIDE_DIRECT_START: "direct start (override the profile)",
}

# PanelLoadbalancing.m_compliantRandomDelay: below this the station is no
# longer compliant, and the app says so rather than refusing the write.
COMPLIANT_RANDOM_DELAY_S = 600
MAX_RANDOM_DELAY_S = 3600


class ChargingProfileError(AlfenError):
    """A direct-start or randomised-delay setting the charger will not take."""


@dataclass
class DirectStart:
    """What the station is doing with an installed profile, per socket."""

    overrides: dict[int, int] = field(default_factory=dict)
    """Socket number to :data:`OVERRIDE_FOLLOW` / :data:`OVERRIDE_DIRECT_START`."""

    random_delay_s: int | None = None
    """The randomised start delay the profile applies, in seconds."""

    types: dict[tuple[int, int], int] = field(default_factory=dict)
    """The charger's own type for each register, for writing them back."""

    def rows(self) -> list[tuple[str, str]]:
        """Render as label/value rows."""
        out: list[tuple[str, str]] = []
        for number, value in sorted(self.overrides.items()):
            out.append(
                (f"Socket {number}", OVERRIDE_LABELS.get(value, f"unknown ({value})"))
            )
        if self.random_delay_s is not None:
            note = (
                ""
                if self.random_delay_s >= COMPLIANT_RANDOM_DELAY_S
                else f" (below the compliant {COMPLIANT_RANDOM_DELAY_S} s)"
            )
            out.append(("Random delay", f"{self.random_delay_s} s{note}"))
        return out


def read_direct_start(charger: AlfenCharger) -> DirectStart:
    """Read the per-socket override and the randomised delay in one call."""
    keys = [*SOCKET_OVERRIDE.values(), P_RANDOM_DELAY]
    live = {prop.key: prop for prop in charger.fetch_properties_by_ids(keys)}
    overrides: dict[int, int] = {}
    for number, key in SOCKET_OVERRIDE.items():
        raw = _whole_number(live.get(key))
        if raw is not None:
            overrides[number] = raw
    return DirectStart(
        overrides=overrides,
        random_delay_s=_whole_number(live.get(P_RANDOM_DELAY)),
        types={
            key: prop.data_type
            for key, prop in live.items()
            if prop.data_type is not None
        },
    )


def check_random_delay(seconds: int) -> int:
    """Return ``seconds`` if it is a randomised delay the firmware accepts."""
    if seconds < 0 or seconds > MAX_RANDOM_DELAY_S:
        raise ChargingProfileError(
            f"the random delay must be between 0 and {MAX_RANDOM_DELAY_S} seconds"
        )
    return int(seconds)


def set_direct_start(
    charger: AlfenCharger,
    *,
    sockets: dict[int, bool] | None = None,
    random_delay_s: int | None = None,
    state: DirectStart | None = None,
) -> DirectStart:
    """Turn direct start on or off per socket, and return the new state."""
    if not sockets and random_delay_s is None:
        raise ChargingProfileError("nothing to set")
    if state is None:
        state = read_direct_start(charger)
    writes: dict[tuple[int, int], tuple[Any, int | None]] = {}
    for number, direct in (sockets or {}).items():
        key = SOCKET_OVERRIDE.get(number)
        if key is None:
            raise ChargingProfileError(
                f"there is no socket {number} on an Alfen station"
            )
        value = OVERRIDE_DIRECT_START if direct else OVERRIDE_FOLLOW
        writes[key] = (value, state.types.get(key) or UNSIGNED8)
    if random_delay_s is not None:
        writes[P_RANDOM_DELAY] = (
            check_random_delay(random_delay_s),
            state.types.get(P_RANDOM_DELAY) or UNSIGNED32,
        )
    charger.write_properties(writes)
    return read_direct_start(charger)


def _whole_number(prop: Any) -> int | None:
    """Return a live property's value as an int, or None when it has none."""
    if prop is None or prop.value is None:
        return None
    try:
        return int(float(prop.value))
    except (TypeError, ValueError):
        return None
