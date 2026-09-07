"""The settings a station is installed with: where it is and how it behaves.

Six registers nobody reads on purpose, all of them answers to the question
"what did the installer set this one up as?" -- the position it was given
(``sysPosition``, the same pair My Eve pins on a map), the language on its
display, how long it has been up since its last reboot, the load-balancing
mode it was licensed and configured for, and the price it shows on screen.

None of these are in the category walk, so they are read by one explicit
``ids=`` query, the way the clock, hardware and license blocks are -- and a
charger that does not answer for some of them simply reports none, the way
those blocks tolerate a missing modem or a missing feature list.
"""

from __future__ import annotations

from dataclasses import dataclass

from alfenctl.charger import AlfenCharger, LiveProperty
from alfenctl.values import as_int

P_LATITUDE = (0x205C, 1)  # 8284 sub 1 sysPosition:latitude
P_LONGITUDE = (0x205C, 2)  # 8284 sub 2 sysPosition:longitude
P_LANGUAGE = (0x205D, 0)  # 8285 sysLanguage, an IETF-ish tag ("en_GB")
P_UPTIME = (0x2060, 0)  # 8288 sysUpTime, MILLIseconds since the last reboot
P_LOAD_BALANCING = (0x2064, 0)  # 8292 sysLoadBalancingMode
P_SMART_CHARGING = (0x2065, 1)  # 8293 sub 1, the Smart Charging Mode flag
# The on-screen pricing block (OD_dispDisplayPricing.*): the currency's
# three-letter code, a start price, and the two per-unit prices.
P_PRICE_CURRENCY = (0x3262, 1)
P_PRICE_START = (0x3262, 2)
P_PRICE_PER_KWH = (0x3262, 3)
P_PRICE_PER_MINUTE = (0x3262, 4)

ALL_KEYS = (
    P_LATITUDE,
    P_LONGITUDE,
    P_LANGUAGE,
    P_UPTIME,
    P_LOAD_BALANCING,
    P_SMART_CHARGING,
    P_PRICE_CURRENCY,
    P_PRICE_START,
    P_PRICE_PER_KWH,
    P_PRICE_PER_MINUTE,
)

# ELoadBalancingMode: bit 0 static, bit 1 active (the EDS numbers the four
# combinations 0-3, My Eve's setup wizard flips the same two bits).
STATIC_BIT = 0x1
ACTIVE_BIT = 0x2

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# `sysUpTime` counts milliseconds, whatever its name and the EDS suggest.
#
# Nothing says so in words: the vendor's own installer labels the register
# "System uptime (s)".  Three things say so in numbers.  It is declared as
# a 64-bit integer (type 27, the same class as `sysDateTime` next door,
# which is milliseconds since the epoch) -- 32 bits would carry 136 years
# of seconds and would not need the width, while milliseconds overflow it
# in seven weeks.  The Home Assistant integration, which is reading the
# same charger over the same API, gives the sensor
# `UnitOfTime.MILLISECONDS` and its own fixture calls 3600000 "1 hour in
# ms".  And a station rebooted the same morning read 43,000,000-odd, which
# is twelve hours of milliseconds and five hundred days of seconds.
#
# Taken as seconds it made every charger on the dashboard look as though it
# had been up since before it was manufactured.
MS_PER_SECOND = 1000


@dataclass(frozen=True)
class Setup:
    """What this station was configured as, at installation time."""

    latitude: float | None = None
    longitude: float | None = None
    language: str | None = None
    uptime_s: int | None = None
    load_balancing: int | None = None
    smart_charging: bool | None = None
    price_currency: str | None = None
    price_start: float | None = None
    price_per_kwh: float | None = None
    price_per_minute: float | None = None

    def format_uptime(self) -> str:
        """Render the uptime in the largest whole unit that still says something.

        An uptime is read as "has it been rebooted", not as a stopwatch
        reading: 144 days, not 144 days 11 hours 50 minutes 57 seconds.
        """
        seconds = self.uptime_s
        if seconds is None or seconds < 0:
            return ""
        if seconds < SECONDS_PER_MINUTE:
            return f"{seconds} s"
        if seconds < SECONDS_PER_DAY:
            hours, rem = divmod(seconds, SECONDS_PER_HOUR)
            if not hours:
                return f"{rem // SECONDS_PER_MINUTE} min"
            minutes = rem // SECONDS_PER_MINUTE
            return f"{hours} h {minutes} min" if minutes else f"{hours} h"
        days, rem = divmod(seconds, SECONDS_PER_DAY)
        hours = rem // SECONDS_PER_HOUR
        return f"{days} d {hours} h" if hours else f"{days} d"

    def load_balancing_label(self) -> str:
        """Render the balancing mode as its two switches ("static on, active on").

        The number alone answers nothing -- 3 is every license bit set, not
        a mode anyone chose -- and the EDS's own four titles spell out both
        switches anyway.  A value outside 0-3 is kept as the raw number,
        which is what the property browser does with an unknown code too.
        """
        mode = self.load_balancing
        if mode is None:
            return ""
        if mode not in (0, 1, 2, 3):
            return f"unknown ({mode})"
        static = "on" if mode & STATIC_BIT else "off"
        active = "on" if mode & ACTIVE_BIT else "off"
        return f"static {static}, active {active}"


def _number(live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]):
    """Return one live property's value as a number, or None if absent."""
    prop = live.get(key)
    if prop is None or prop.value is None or prop.value == "":
        return None
    try:
        return float(prop.value)
    except (TypeError, ValueError):
        return None


def _text(live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]):
    """Return one live property's value as a trimmed string, or None."""
    prop = live.get(key)
    if prop is None:
        return None
    text = str(prop.value or "").strip()
    return text or None


def _uptime_seconds(raw: float | None) -> int | None:
    """Return `sysUpTime` in seconds, from the milliseconds it is kept in."""
    return None if raw is None else as_int(raw / MS_PER_SECOND)


def read(charger: AlfenCharger) -> Setup:
    """Read the installation settings, tolerating a charger that reports none."""
    live = {lp.key: lp for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}
    smart = _number(live, P_SMART_CHARGING)
    return Setup(
        latitude=_number(live, P_LATITUDE),
        longitude=_number(live, P_LONGITUDE),
        language=_text(live, P_LANGUAGE),
        uptime_s=_uptime_seconds(_number(live, P_UPTIME)),
        load_balancing=as_int(_number(live, P_LOAD_BALANCING)),
        smart_charging=None if smart is None else bool(smart),
        price_currency=_text(live, P_PRICE_CURRENCY),
        price_start=_number(live, P_PRICE_START),
        price_per_kwh=_number(live, P_PRICE_PER_KWH),
        price_per_minute=_number(live, P_PRICE_PER_MINUTE),
    )
