"""The backoffice connection: which CSMS, over what, and how talkative.

The app's *Connectivity* panel is its largest, and most of it is one subject:
how this charger reaches its central system and what it says once it gets
there.  The registers are ordinary properties, but two things about them are
not obvious from an id.

**Most of them are not in the EDS.**  The bundled catalog describes the
back-office URLs, the protocol version and the heartbeat, and says nothing
about the proxy, the timeouts, the status-notification settings or the OCPP
security profile -- so there is no declared type to encode a write with.  The
charger itself supplies one, in the ``type`` field of every property it
answers with, and that is what :func:`apply` writes back with: the live
metadata is the authority on what a property *is*, the same rule
:mod:`alfenctl.values` follows.

**The heartbeat is two registers, one of them read-only.**  0x2085 is the
interval this charger asks for and 0x2086 the one it and the backoffice
settled on; the EDS marks the second ``ro``.  Writing to 0x2086 -- which one
of the reverse-engineered sources does -- changes nothing, so this module
writes 0x2085 and reports both.

The authorization key and the proxy *password* are not properties at all:
they are write-only domain items, and ``alfenctl secret set`` already installs
them.  Nothing here duplicates that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from alfenctl.charger import AlfenCharger, LiveProperty
from alfenctl.eds import INTEGER16, UNSIGNED32, VISIBLE_STRING
from alfenctl.errors import AlfenError

# --- the registers -----------------------------------------------------------------------
P_BACKOFFICE_NAME = (0x2076, 0)  # 8310 commBackOfficeShortName, the preset's name
P_CONNECT_METHOD = (0x2077, 0)  # 8311 commConnectMethod
P_PROTOCOL = (0x2082, 0)  # 8322 commProtocolVersion, a string like "1.6"
P_WIRED_URL = (0x2071, 1)  # 8305 sub 1, host and port
P_WIRED_PATH = (0x2071, 2)  # 8305 sub 2
P_MOBILE_URL = (0x2078, 1)  # 8312 sub 1
P_MOBILE_PATH = (0x2078, 2)  # 8312 sub 2
P_HEARTBEAT = (0x2085, 0)  # 8325 commDefaultHeartBeatInterval, the one to write
P_HEARTBEAT_ACTUAL = (0x2086, 0)  # 8326 commActualHeartBeatInterval, read-only
P_PING_PONG = (0x208A, 0)  # 8330 commPingPongInterval
P_SEND_TIMEOUT_WIRED = (0x208D, 1)  # 8333 sub 1
P_SEND_TIMEOUT_MOBILE = (0x208D, 2)  # 8333 sub 2
P_REPLY_TIMEOUT_WIRED = (0x208E, 1)  # 8334 sub 1
P_REPLY_TIMEOUT_MOBILE = (0x208E, 2)  # 8334 sub 2
P_SEND_STATION_STATUS = (0x2093, 0)  # 8339
P_STATUS_MODE = (0x209C, 0)  # 8348
P_INFO_NOTIFICATIONS = (0x2124, 0)  # 8484
P_METER_INTERVAL = (0x2087, 0)  # 8327 commMeteringInterval, seconds
P_ALIGNED_INTERVAL = (0x209A, 0)  # 8346 clock-aligned interval, seconds
P_TX_ATTEMPTS = (0x2096, 0)  # 8342 transaction message attempts
P_TX_RETRY_S = (0x2097, 0)  # 8343 retry interval
P_CPO_NAME = (0x2722, 0)  # 10018 the operator's name on the certificate
P_SECURITY_PROFILE = (0x2723, 0)  # 10019
P_PROXY_ENABLED = (0x2117, 0)  # 8471
P_PROXY_ADDRESS = (0x2115, 0)  # 8469 address and port
P_PROXY_USER = (0x2116, 0)  # 8470

ALL_KEYS = (
    P_BACKOFFICE_NAME,
    P_CONNECT_METHOD,
    P_PROTOCOL,
    P_WIRED_URL,
    P_WIRED_PATH,
    P_MOBILE_URL,
    P_MOBILE_PATH,
    P_HEARTBEAT,
    P_HEARTBEAT_ACTUAL,
    P_PING_PONG,
    P_SEND_TIMEOUT_WIRED,
    P_SEND_TIMEOUT_MOBILE,
    P_REPLY_TIMEOUT_WIRED,
    P_REPLY_TIMEOUT_MOBILE,
    P_SEND_STATION_STATUS,
    P_STATUS_MODE,
    P_INFO_NOTIFICATIONS,
    P_METER_INTERVAL,
    P_ALIGNED_INTERVAL,
    P_TX_ATTEMPTS,
    P_TX_RETRY_S,
    P_CPO_NAME,
    P_SECURITY_PROFILE,
    P_PROXY_ENABLED,
    P_PROXY_ADDRESS,
    P_PROXY_USER,
)

# What to encode a write as when the charger did not report a type -- which
# only happens for a property it does not have, where the write fails anyway.
FALLBACK_TYPES: dict[tuple[int, int], int] = {
    P_CONNECT_METHOD: INTEGER16,
    P_PROTOCOL: VISIBLE_STRING,
    P_WIRED_URL: VISIBLE_STRING,
    P_WIRED_PATH: VISIBLE_STRING,
    P_MOBILE_URL: VISIBLE_STRING,
    P_MOBILE_PATH: VISIBLE_STRING,
    P_HEARTBEAT: UNSIGNED32,
    P_PING_PONG: UNSIGNED32,
    P_SEND_TIMEOUT_WIRED: UNSIGNED32,
    P_SEND_TIMEOUT_MOBILE: UNSIGNED32,
    P_REPLY_TIMEOUT_WIRED: UNSIGNED32,
    P_REPLY_TIMEOUT_MOBILE: UNSIGNED32,
    P_SEND_STATION_STATUS: INTEGER16,
    P_STATUS_MODE: INTEGER16,
    P_INFO_NOTIFICATIONS: INTEGER16,
    P_METER_INTERVAL: UNSIGNED32,
    P_ALIGNED_INTERVAL: UNSIGNED32,
    P_TX_ATTEMPTS: UNSIGNED32,
    P_TX_RETRY_S: UNSIGNED32,
    P_CPO_NAME: VISIBLE_STRING,
    P_SECURITY_PROFILE: INTEGER16,
    P_PROXY_ENABLED: INTEGER16,
    P_PROXY_ADDRESS: VISIBLE_STRING,
    P_PROXY_USER: VISIBLE_STRING,
}

# commConnectMethod.  A charger may answer 99 for "automatic", which the app
# folds onto 3 before it shows the dropdown.
CONNECT_AUTOMATIC_RAW = 99
CONNECT_METHODS = {0: "none", 1: "wired", 2: "mobile", 3: "automatic"}

# The OCPP versions the charger will speak.  A string register, not an index.
PROTOCOLS = ("1.5", "1.6", "2.0.1")

# The OCPP 1.6 security profiles, as the app's dropdown names them.
SECURITY_PROFILES = {
    0: "unsecured, no authentication",
    1: "unsecured with basic authentication",
    2: "TLS with basic authentication",
    3: "TLS with a client certificate",
}

# EBackOfficeStatusNotificationModeType.
STATUS_MODES = {0: "immediate", 1: "immediate with a timestamp", 2: "queued"}

MAX_INTERVAL_S = 86400


class OcppError(AlfenError, ValueError):
    """An OCPP setting the charger could not sensibly be given."""


@dataclass
class Ocpp:
    """How this charger talks to its central system."""

    backoffice_name: str | None = None
    connect_method: int | None = None
    protocol: str | None = None
    wired_url: str | None = None
    wired_path: str | None = None
    mobile_url: str | None = None
    mobile_path: str | None = None
    heartbeat_s: int | None = None
    heartbeat_actual_s: int | None = None
    ping_pong_s: int | None = None
    send_timeout_s: tuple[int | None, int | None] = (None, None)
    reply_timeout_s: tuple[int | None, int | None] = (None, None)
    send_station_status: bool | None = None
    status_mode: int | None = None
    info_notifications: bool | None = None
    meter_interval_s: int | None = None
    aligned_interval_s: int | None = None
    tx_attempts: int | None = None
    tx_retry_s: int | None = None
    cpo_name: str | None = None
    security_profile: int | None = None
    proxy_enabled: bool | None = None
    proxy_address: str | None = None
    proxy_user: str | None = None
    types: dict[tuple[int, int], int] = field(default_factory=dict)
    """What the charger said each property's type is, for writing it back."""

    def warnings(self) -> list[str]:
        """Return what is configured but cannot work, in the app's own terms."""
        out: list[str] = []
        if self.connect_method == 0 and (self.wired_url or self.mobile_url):
            out.append(
                "a back-office URL is set, but the connect method is none, so "
                "the charger will not dial out"
            )
        if self.security_profile in (2, 3) and not self.cpo_name:
            out.append(
                "a TLS security profile is selected with no CPO name, which is "
                "the name the charger checks the certificate against"
            )
        if self.proxy_enabled and not self.proxy_address:
            out.append("the proxy is enabled with no address set")
        if (
            self.heartbeat_s is not None
            and self.heartbeat_actual_s is not None
            and self.heartbeat_s != self.heartbeat_actual_s
        ):
            out.append(
                f"the backoffice settled on a {self.heartbeat_actual_s} s "
                f"heartbeat rather than the {self.heartbeat_s} s configured"
            )
        return out

    def rows(self) -> list[tuple[str, str]]:
        """Return the label/value pairs worth printing, skipping what is absent."""
        out: list[tuple[str, str]] = []
        if self.backoffice_name:
            out.append(("Back office", self.backoffice_name))
        if self.connect_method is not None:
            out.append(("Connect method", _label(CONNECT_METHODS, self.connect_method)))
        if self.protocol:
            out.append(("OCPP version", self.protocol))
        for label, url, path in (
            ("Wired URL", self.wired_url, self.wired_path),
            ("Mobile URL", self.mobile_url, self.mobile_path),
        ):
            if url:
                out.append((label, f"{url}/{path}" if path else url))
        if self.security_profile is not None:
            out.append(
                ("Security profile", _label(SECURITY_PROFILES, self.security_profile))
            )
        if self.cpo_name:
            out.append(("CPO name", self.cpo_name))
        if self.heartbeat_s is not None:
            actual = self.heartbeat_actual_s
            note = "" if actual in (None, self.heartbeat_s) else f" (actual {actual} s)"
            out.append(("Heartbeat", f"{self.heartbeat_s} s{note}"))
        for label, seconds in (
            ("Ping/pong", self.ping_pong_s),
            ("Meter interval", self.meter_interval_s),
            ("Aligned interval", self.aligned_interval_s),
            ("Retry interval", self.tx_retry_s),
        ):
            if seconds is not None:
                out.append((label, f"{seconds} s"))
        for label, pair in (
            ("Send timeout", self.send_timeout_s),
            ("Reply timeout", self.reply_timeout_s),
        ):
            wired, mobile = pair
            if wired is not None or mobile is not None:
                out.append((label, f"{wired} s wired, {mobile} s mobile"))
        if self.tx_attempts is not None:
            out.append(("Message attempts", str(self.tx_attempts)))
        if self.status_mode is not None:
            out.append(("Status notification", _label(STATUS_MODES, self.status_mode)))
        for label, flag in (
            ("Send station status", self.send_station_status),
            ("Informational notices", self.info_notifications),
        ):
            if flag is not None:
                out.append((label, "enabled" if flag else "disabled"))
        if self.proxy_enabled is not None:
            out.append(("Proxy", "enabled" if self.proxy_enabled else "disabled"))
            if self.proxy_address:
                out.append(("  address", self.proxy_address))
            if self.proxy_user:
                out.append(("  user", self.proxy_user))
        return out


def _label(table: dict[int, str], code: int) -> str:
    """Look up a code, keeping the raw number when the table lacks it."""
    return table.get(code, f"unknown ({code})")


def _int(live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]) -> int | None:
    """Read a property as an integer, or None when absent or not numeric."""
    prop = live.get(key)
    if prop is None or prop.value is None:
        return None
    try:
        return int(float(prop.value))
    except (TypeError, ValueError):
        return None


def _flag(
    live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]
) -> bool | None:
    """Read a property as a boolean, or None when the charger did not answer."""
    value = _int(live, key)
    return None if value is None else bool(value)


def _text(
    live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]
) -> str | None:
    """Read a property as a non-empty string, or None."""
    prop = live.get(key)
    if prop is None or prop.value in (None, ""):
        return None
    return str(prop.value)


def read(charger: AlfenCharger) -> Ocpp:
    """Read every back-office register in one ``ids=`` query."""
    live = {lp.key: lp for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}
    method = _int(live, P_CONNECT_METHOD)
    if method == CONNECT_AUTOMATIC_RAW:
        method = 3
    return Ocpp(
        backoffice_name=_text(live, P_BACKOFFICE_NAME),
        connect_method=method,
        protocol=_text(live, P_PROTOCOL),
        wired_url=_text(live, P_WIRED_URL),
        wired_path=_text(live, P_WIRED_PATH),
        mobile_url=_text(live, P_MOBILE_URL),
        mobile_path=_text(live, P_MOBILE_PATH),
        heartbeat_s=_int(live, P_HEARTBEAT),
        heartbeat_actual_s=_int(live, P_HEARTBEAT_ACTUAL),
        ping_pong_s=_int(live, P_PING_PONG),
        send_timeout_s=(
            _int(live, P_SEND_TIMEOUT_WIRED),
            _int(live, P_SEND_TIMEOUT_MOBILE),
        ),
        reply_timeout_s=(
            _int(live, P_REPLY_TIMEOUT_WIRED),
            _int(live, P_REPLY_TIMEOUT_MOBILE),
        ),
        send_station_status=_flag(live, P_SEND_STATION_STATUS),
        status_mode=_int(live, P_STATUS_MODE),
        info_notifications=_flag(live, P_INFO_NOTIFICATIONS),
        meter_interval_s=_int(live, P_METER_INTERVAL),
        aligned_interval_s=_int(live, P_ALIGNED_INTERVAL),
        tx_attempts=_int(live, P_TX_ATTEMPTS),
        tx_retry_s=_int(live, P_TX_RETRY_S),
        cpo_name=_text(live, P_CPO_NAME),
        security_profile=_int(live, P_SECURITY_PROFILE),
        proxy_enabled=_flag(live, P_PROXY_ENABLED),
        proxy_address=_text(live, P_PROXY_ADDRESS),
        proxy_user=_text(live, P_PROXY_USER),
        types={
            key: prop.data_type
            for key, prop in live.items()
            if prop.data_type is not None
        },
    )


def _interval(seconds: int, what: str) -> int:
    """Return ``seconds`` if it is an interval the charger will honour."""
    if not 0 <= seconds <= MAX_INTERVAL_S:
        raise OcppError(f"{what} must be between 0 and {MAX_INTERVAL_S} s")
    return int(seconds)


def apply(
    charger: AlfenCharger,
    *,
    connect_method: int | None = None,
    protocol: str | None = None,
    wired_url: str | None = None,
    wired_path: str | None = None,
    mobile_url: str | None = None,
    mobile_path: str | None = None,
    heartbeat_s: int | None = None,
    ping_pong_s: int | None = None,
    meter_interval_s: int | None = None,
    aligned_interval_s: int | None = None,
    send_station_status: bool | None = None,
    status_mode: int | None = None,
    info_notifications: bool | None = None,
    tx_attempts: int | None = None,
    tx_retry_s: int | None = None,
    cpo_name: str | None = None,
    security_profile: int | None = None,
    proxy_enabled: bool | None = None,
    proxy_address: str | None = None,
    proxy_user: str | None = None,
    state: Ocpp | None = None,
) -> Ocpp:
    """Write the settings that were named, and return the charger's new state.

    Most of these have no EDS entry, so each write is encoded with the type
    the charger itself reported for that property; ``state`` is the reading
    that carries those types, and is taken fresh when it was not supplied.
    """
    if state is None:
        state = read(charger)
    plain: dict[tuple[int, int], Any] = {}
    if connect_method is not None:
        if connect_method not in CONNECT_METHODS:
            raise OcppError(
                "the connect method is "
                + ", ".join(f"{v} ({n})" for v, n in sorted(CONNECT_METHODS.items()))
            )
        plain[P_CONNECT_METHOD] = connect_method
    if protocol is not None:
        if protocol not in PROTOCOLS:
            raise OcppError(f"the OCPP version is one of {', '.join(PROTOCOLS)}")
        plain[P_PROTOCOL] = protocol
    for value, key in (
        (wired_url, P_WIRED_URL),
        (wired_path, P_WIRED_PATH),
        (mobile_url, P_MOBILE_URL),
        (mobile_path, P_MOBILE_PATH),
        (cpo_name, P_CPO_NAME),
        (proxy_address, P_PROXY_ADDRESS),
        (proxy_user, P_PROXY_USER),
    ):
        if value is not None:
            plain[key] = value
    for seconds, key, what in (
        (heartbeat_s, P_HEARTBEAT, "the heartbeat interval"),
        (ping_pong_s, P_PING_PONG, "the ping/pong interval"),
        (meter_interval_s, P_METER_INTERVAL, "the meter interval"),
        (aligned_interval_s, P_ALIGNED_INTERVAL, "the clock-aligned interval"),
        (tx_retry_s, P_TX_RETRY_S, "the retry interval"),
    ):
        if seconds is not None:
            plain[key] = _interval(seconds, what)
    for flag, key in (
        (send_station_status, P_SEND_STATION_STATUS),
        (info_notifications, P_INFO_NOTIFICATIONS),
        (proxy_enabled, P_PROXY_ENABLED),
    ):
        if flag is not None:
            plain[key] = int(flag)
    if status_mode is not None:
        if status_mode not in STATUS_MODES:
            raise OcppError(f"unknown status notification mode {status_mode}")
        plain[P_STATUS_MODE] = status_mode
    if security_profile is not None:
        if security_profile not in SECURITY_PROFILES:
            raise OcppError(
                "the security profile is "
                + ", ".join(f"{v} ({n})" for v, n in sorted(SECURITY_PROFILES.items()))
            )
        plain[P_SECURITY_PROFILE] = security_profile
    if tx_attempts is not None:
        if tx_attempts < 0:
            raise OcppError("the message attempts cannot be negative")
        plain[P_TX_ATTEMPTS] = tx_attempts
    if plain:
        charger.write_properties(
            {
                key: (value, state.types.get(key) or FALLBACK_TYPES.get(key))
                for key, value in plain.items()
            }
        )
    return read(charger)


__all__ = [
    "ALL_KEYS",
    "CONNECT_METHODS",
    "Ocpp",
    "OcppError",
    "PROTOCOLS",
    "SECURITY_PROFILES",
    "STATUS_MODES",
    "apply",
    "read",
]
