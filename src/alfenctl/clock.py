"""The charger's own clock: read it, and set it from this computer.

``sysDateTime`` (0x2059) is milliseconds since the Unix epoch, in UTC.  The
charger displays and stamps its logs in local time, which it derives from a
time-zone offset held in one of two properties depending on firmware:
``sysTimeZoneMinutes`` (0x206E) in whole minutes on newer builds, else
``sysTimeZone`` (0x205A) in units of six minutes -- the app picks between
them exactly this way (``PanelInformation``, ``OnSyncTimeClicked``).
``sysDaylightSavings`` (0x205B) says whether the charger adds an hour by
itself.

None of these are in the category walk, so they are read by explicit
``ids=`` query, like the license and master-tag properties.

Why it matters beyond tidiness: a charger boots with its RTC at the firmware
build date and only jumps forward once something sets it, so an unsynced
station stamps its event log and its transaction records with a time that
may be years out -- and firmware signature validation checks certificate
validity against that same clock, which is why an upload sets it too (see
``AlfenCharger.set_datetime``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from alfenctl.charger import AlfenCharger, LiveProperty

P_DATE_TIME = (0x2059, 0)  # 8281 sysDateTime, ms since the Unix epoch (UTC)
P_TIME_ZONE = (0x205A, 0)  # 8282 sysTimeZone, in units of six minutes
P_DAYLIGHT_SAVINGS = (0x205B, 0)  # 8283 sysDaylightSavings
P_TIME_ZONE_MINUTES = (0x206E, 0)  # 8302 sysTimeZoneMinutes

ALL_KEYS = (P_DATE_TIME, P_TIME_ZONE, P_DAYLIGHT_SAVINGS, P_TIME_ZONE_MINUTES)

MS_PER_SECOND = 1000
# sysTimeZone counts in six-minute steps (+10 == UTC+1); sysTimeZoneMinutes
# in whole minutes.  Newer firmware carries both, and the minutes one wins.
TIME_ZONE_STEP_MINUTES = 6

# Below this the clocks are as good as identical.  The charger is told the
# time in whole seconds, so it can never be nearer than half a second, and
# what is left after that is the jitter of the read itself.
DRIFT_NOISE_S = 2.0

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
SECONDS_PER_YEAR = 365 * SECONDS_PER_DAY


@dataclass(frozen=True)
class Clock:
    """What the charger reports about its own time."""

    utc: datetime | None
    """The charger's clock in UTC, or None if it does not report one."""

    offset: timedelta | None
    """The configured time-zone offset from UTC, or None if not reported."""

    daylight_savings: bool | None
    """Whether the charger applies daylight saving on top of the offset."""

    measured_at: datetime | None = None
    """This computer's time at the instant :attr:`utc` was sampled.

    The charger reads its clock somewhere inside the request, so the honest
    local counterpart is the middle of the round trip, not the moment the
    answer finished arriving.  Comparing against the latter made every
    charger look like it lagged by one round trip -- a second or three, even
    on a station that had just been synced.
    """

    @property
    def local(self) -> datetime | None:
        """The charger's own local time, as it would show on its display."""
        if self.utc is None or self.offset is None:
            return None
        return (self.utc + self.offset).replace(tzinfo=None)

    def drift(self, *, now: datetime | None = None) -> timedelta | None:
        """How far the charger's clock is from this computer's.

        Measured against :attr:`measured_at` unless ``now`` says otherwise,
        so the round trip that fetched the reading does not count as drift.
        """
        if self.utc is None:
            return None
        return self.utc - (now or self.measured_at or datetime.now(timezone.utc))


def _number(live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]):
    """Return one live property's value as a number, or None if absent."""
    prop = live.get(key)
    if prop is None or prop.value is None or prop.value == "":
        return None
    try:
        return float(prop.value)
    except (TypeError, ValueError):
        return None


def read(charger: AlfenCharger) -> Clock:
    """Read the charger's clock and time-zone settings."""
    before = datetime.now(timezone.utc)
    live = {lp.key: lp for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}
    after = datetime.now(timezone.utc)
    epoch_ms = _number(live, P_DATE_TIME)
    utc = None
    if epoch_ms:  # a charger that has never been set reports 0
        try:
            utc = datetime.fromtimestamp(epoch_ms / MS_PER_SECOND, timezone.utc)
        except (OverflowError, OSError, ValueError):
            utc = None
    minutes = _number(live, P_TIME_ZONE_MINUTES)
    if minutes is None:
        steps = _number(live, P_TIME_ZONE)
        minutes = None if steps is None else steps * TIME_ZONE_STEP_MINUTES
    dst = _number(live, P_DAYLIGHT_SAVINGS)
    return Clock(
        utc=utc,
        offset=None if minutes is None else timedelta(minutes=minutes),
        daylight_savings=None if dst is None else bool(dst),
        measured_at=before + (after - before) / 2,
    )


def sync(charger: AlfenCharger, *, is_ahp: bool = False) -> datetime:
    """Set the charger's clock to this computer's, and return what was sent.

    The moment is not chosen here: :meth:`AlfenCharger.set_datetime` stamps
    each request as it goes out, which is the only way the charger ends up
    on time rather than one round trip behind.
    """
    return charger.set_datetime(is_ahp=is_ahp)


def format_offset(offset: timedelta | None) -> str:
    """Render a UTC offset the way people write them ("UTC+02:00")."""
    if offset is None:
        return "<not reported>"
    total = int(offset.total_seconds()) // 60
    sign = "-" if total < 0 else "+"
    hours, minutes = divmod(abs(total), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def format_zone(state: Clock) -> str:
    """Render the zone the charger keeps its local time in, as one line.

    The offset and the daylight-saving flag are two properties but a single
    fact, and read apart they invite the wrong arithmetic: a charger at
    UTC+01:00 with daylight saving on is showing UTC+02:00 on its display.
    """
    zone = format_offset(state.offset)
    if state.daylight_savings is not None:
        zone += ", daylight saving " + ("on" if state.daylight_savings else "off")
    return zone


def format_drift(drift: timedelta | None) -> str:
    """Render the difference between the two clocks in words.

    The scale matters here: an unsynced charger is not seconds out but
    years, since it boots with its RTC at the firmware build date.
    """
    if drift is None:
        return "<charger reports no time>"
    seconds = drift.total_seconds()
    if abs(seconds) < DRIFT_NOISE_S:
        return "in sync with this computer"
    size = abs(seconds)
    if size < SECONDS_PER_MINUTE:
        amount = f"{size:.0f} seconds"
    elif size < SECONDS_PER_HOUR:
        amount = f"{size / SECONDS_PER_MINUTE:.0f} minutes"
    elif size < SECONDS_PER_DAY:
        amount = f"{size / SECONDS_PER_HOUR:.1f} hours"
    elif size < SECONDS_PER_YEAR:
        amount = f"{size / SECONDS_PER_DAY:.1f} days"
    else:
        amount = f"{size / SECONDS_PER_YEAR:.1f} years"
    return f"{amount} {'ahead of' if seconds > 0 else 'behind'} this computer"
