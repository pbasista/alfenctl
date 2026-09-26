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

from devicectl import fields
from devicectl.fields import FieldSpec

from alfenctl.charger import AlfenCharger
from alfenctl.connectivity import P_APN
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

# The GPRS credentials that travel with a backoffice, named here because
# clearing a preset clears them with it (see :data:`BACKOFFICE_CLEARED`).
P_APN_USER = (0x2101, 0)  # 8449 gprsAPNuser
P_APN_PASSWORD = (0x2102, 0)  # 8450 gprsAPNpassword

# The backoffice properties the app empties before it installs a preset, so
# that a leftover URL or APN from the previous operator cannot survive into
# the new one (``PanelConnectivity.ClearAllBackOfficeSettings``).  The four
# network profiles it also clears are left alone: they are a whole panel of
# their own, and clearing them is not what "apply this preset" was asked.
BACKOFFICE_CLEARED = (
    P_WIRED_URL,
    P_WIRED_PATH,
    P_MOBILE_URL,
    P_MOBILE_PATH,
    P_APN,
    P_APN_USER,
    P_APN_PASSWORD,
)

# CombineBopresetMeterName gives up past this.
BACKOFFICE_NAME_MAX = 50
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


def _url_row(value: Any, state: Ocpp) -> str | None:
    """Render a back-office URL with its path, which has no row of its own."""
    if not value:
        return None
    path = state.wired_path if value == state.wired_url else state.mobile_path
    return f"{value}/{path}" if path else str(value)


def _heartbeat_row(value: Any, state: Ocpp) -> str | None:
    """Render the heartbeat asked for, and the one the backoffice settled on."""
    if value is None:
        return None
    actual = state.heartbeat_actual_s
    note = "" if actual in (None, value) else f" (actual {actual} s)"
    return f"{value} s{note}"


def _pair_row(value: Any, _state: Ocpp) -> str | None:
    """Render a wired/mobile pair of timeouts as the one row the app shows."""
    wired, mobile = value
    if wired is None and mobile is None:
        return None
    return f"{wired} s wired, {mobile} s mobile"


def _interval(**over: Any) -> dict[str, Any]:
    """Return the keywords every one of the five interval fields shares."""
    return {
        "kind": fields.INTEGER,
        "wire": UNSIGNED32,
        "unit": "s",
        "minimum": 0,
        "maximum": MAX_INTERVAL_S,
        "metavar": "S",
        **over,
    }


# --- the settings ------------------------------------------------------------------------
# In the order the terminal prints them, and the one place any audience is
# told about a field.  :attr:`FieldSpec.wire` here is only the *fallback*: most
# of these registers are absent from the bundled EDS, so :func:`apply` encodes
# each write with the type the charger itself reported and falls back to this
# when it reported none -- which only happens for a property the station does
# not have, where the write fails anyway.
#
# The three composite rows keep their own renderers: a URL prints with the path
# beside it, the heartbeat prints the negotiated value next to the configured
# one, and the two timeouts are a wired/mobile pair the app shows as one line.
FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        name="backoffice_name",
        kind=fields.TEXT,
        address=P_BACKOFFICE_NAME,
        label="Back office",
        json="backofficeName",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="connect_method",
        kind=fields.ENUM,
        address=P_CONNECT_METHOD,
        wire=INTEGER16,
        label="Connect method",
        json="connectMethod",
        flag="--connect-method",
        options=CONNECT_METHODS,
        what="the connect method",
        help="how to dial out",
    ),
    FieldSpec(
        name="protocol",
        kind=fields.TEXT,
        address=P_PROTOCOL,
        wire=VISIBLE_STRING,
        label="OCPP version",
        json="protocol",
        flag="--protocol",
        options=PROTOCOLS,
        what="the OCPP version",
        help="the OCPP version",
    ),
    FieldSpec(
        name="wired_url",
        kind=fields.TEXT,
        address=P_WIRED_URL,
        wire=VISIBLE_STRING,
        label="Wired URL",
        json="wiredUrl",
        flag="--wired-url",
        metavar="URL",
        what="the wired back-office URL",
        help="the CSMS host and port, wired",
        render=_url_row,
    ),
    FieldSpec(
        name="wired_path",
        kind=fields.TEXT,
        address=P_WIRED_PATH,
        wire=VISIBLE_STRING,
        json="wiredPath",
        flag="--wired-path",
        metavar="PATH",
        what="the wired back-office path",
        help="its path, wired",
    ),
    FieldSpec(
        name="mobile_url",
        kind=fields.TEXT,
        address=P_MOBILE_URL,
        wire=VISIBLE_STRING,
        label="Mobile URL",
        json="mobileUrl",
        flag="--mobile-url",
        metavar="URL",
        what="the mobile back-office URL",
        help="the CSMS host and port, mobile",
        render=_url_row,
    ),
    FieldSpec(
        name="mobile_path",
        kind=fields.TEXT,
        address=P_MOBILE_PATH,
        wire=VISIBLE_STRING,
        json="mobilePath",
        flag="--mobile-path",
        metavar="PATH",
        what="the mobile back-office path",
        help="its path, mobile",
    ),
    FieldSpec(
        name="security_profile",
        kind=fields.ENUM,
        address=P_SECURITY_PROFILE,
        wire=INTEGER16,
        label="Security profile",
        json="securityProfile",
        flag="--security-profile",
        options=SECURITY_PROFILES,
        what="the security profile",
        help="OCPP security",
    ),
    FieldSpec(
        name="cpo_name",
        kind=fields.TEXT,
        address=P_CPO_NAME,
        wire=VISIBLE_STRING,
        label="CPO name",
        json="cpoName",
        flag="--cpo-name",
        metavar="NAME",
        what="the CPO name",
        help="the operator name on the certificate",
    ),
    FieldSpec(
        **_interval(
            name="heartbeat_s",
            address=P_HEARTBEAT,
            label="Heartbeat",
            json="heartbeatS",
            flag="--heartbeat",
            what="the heartbeat interval",
            help="the heartbeat interval to ask for (0x2085_0; the negotiated "
            "one at 0x2086_0 is read-only)",
            render=_heartbeat_row,
        )
    ),
    FieldSpec(
        name="heartbeat_actual_s",
        kind=fields.INTEGER,
        address=P_HEARTBEAT_ACTUAL,
        json="heartbeatActualS",
        unit="s",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        **_interval(
            name="ping_pong_s",
            address=P_PING_PONG,
            label="Ping/pong",
            json="pingPongS",
            flag="--ping-pong",
            what="the ping/pong interval",
            help="websocket ping interval",
        )
    ),
    FieldSpec(
        **_interval(
            name="meter_interval_s",
            address=P_METER_INTERVAL,
            label="Meter interval",
            json="meterIntervalS",
            flag="--meter-interval",
            what="the meter interval",
            help="how often to send meter values",
        )
    ),
    FieldSpec(
        **_interval(
            name="aligned_interval_s",
            address=P_ALIGNED_INTERVAL,
            label="Aligned interval",
            json="alignedIntervalS",
            flag="--aligned-interval",
            what="the clock-aligned interval",
            help="the clock-aligned interval",
        )
    ),
    FieldSpec(
        **_interval(
            name="tx_retry_s",
            address=P_TX_RETRY_S,
            label="Retry interval",
            json="txRetryS",
            flag="--tx-retry",
            what="the retry interval",
            help="the retry interval",
        )
    ),
    FieldSpec(
        name="send_timeout_s",
        label="Send timeout",
        json="sendTimeoutS",
        access=fields.READ_ONLY,
        render=_pair_row,
    ),
    FieldSpec(
        name="reply_timeout_s",
        label="Reply timeout",
        json="replyTimeoutS",
        access=fields.READ_ONLY,
        render=_pair_row,
    ),
    FieldSpec(
        name="tx_attempts",
        kind=fields.INTEGER,
        address=P_TX_ATTEMPTS,
        wire=UNSIGNED32,
        label="Message attempts",
        json="txAttempts",
        flag="--tx-attempts",
        minimum=0,
        metavar="N",
        what="the message attempts",
        help="transaction message attempts",
    ),
    FieldSpec(
        name="status_mode",
        kind=fields.ENUM,
        address=P_STATUS_MODE,
        wire=INTEGER16,
        label="Status notification",
        json="statusMode",
        flag="--status-mode",
        options=STATUS_MODES,
        what="the status notification mode",
        help="status notifications",
    ),
    FieldSpec(
        name="send_station_status",
        kind=fields.FLAG,
        address=P_SEND_STATION_STATUS,
        wire=INTEGER16,
        label="Send station status",
        json="sendStationStatus",
        flag="--send-station-status",
        help="send the station's own status",
    ),
    FieldSpec(
        name="info_notifications",
        kind=fields.FLAG,
        address=P_INFO_NOTIFICATIONS,
        wire=INTEGER16,
        label="Informational notices",
        json="infoNotifications",
        flag="--info-notifications",
        help="send informational notifications",
    ),
    FieldSpec(
        name="proxy_enabled",
        kind=fields.FLAG,
        address=P_PROXY_ENABLED,
        wire=INTEGER16,
        label="Proxy",
        json="proxyEnabled",
        flag="--proxy",
        help="use an HTTP proxy",
    ),
    FieldSpec(
        name="proxy_address",
        kind=fields.TEXT,
        address=P_PROXY_ADDRESS,
        wire=VISIBLE_STRING,
        label="  address",
        json="proxyAddress",
        flag="--proxy-address",
        metavar="HOST:PORT",
        what="the proxy address",
        help="the proxy's address",
    ),
    FieldSpec(
        name="proxy_user",
        kind=fields.TEXT,
        address=P_PROXY_USER,
        wire=VISIBLE_STRING,
        label="  user",
        json="proxyUser",
        flag="--proxy-user",
        metavar="NAME",
        what="the proxy user",
        help="the proxy user name",
    ),
)

# The two timeouts are a wired/mobile pair each, so they are four registers
# behind two fields and are asked for by name rather than through the table.
TIMEOUT_KEYS = (
    P_SEND_TIMEOUT_WIRED,
    P_SEND_TIMEOUT_MOBILE,
    P_REPLY_TIMEOUT_WIRED,
    P_REPLY_TIMEOUT_MOBILE,
)

ALL_KEYS = (
    *(spec.address for spec in FIELDS if spec.address is not None),
    *TIMEOUT_KEYS,
)


class OcppError(AlfenError, fields.FieldError):
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
        return fields.rows(FIELDS, self)


def read(charger: AlfenCharger) -> Ocpp:
    """Read every back-office register in one ``ids=`` query."""
    live = {lp.key: lp for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}

    def answer(key: tuple[int, int]) -> Any:
        prop = live.get(key)
        return None if prop is None else prop.value

    def seconds(key: tuple[int, int]) -> int | None:
        value = answer(key)
        try:
            return None if value is None or value == "" else int(float(value))
        except (TypeError, ValueError):
            return None

    state = Ocpp(**fields.harvest(FIELDS, answer))
    # The app folds the charger's 99 onto its own "automatic" before it draws
    # the dropdown, and so does this, so one meaning has one number here.
    if state.connect_method == CONNECT_AUTOMATIC_RAW:
        state.connect_method = 3
    state.send_timeout_s = (
        seconds(P_SEND_TIMEOUT_WIRED),
        seconds(P_SEND_TIMEOUT_MOBILE),
    )
    state.reply_timeout_s = (
        seconds(P_REPLY_TIMEOUT_WIRED),
        seconds(P_REPLY_TIMEOUT_MOBILE),
    )
    state.types = {
        key: prop.data_type for key, prop in live.items() if prop.data_type is not None
    }
    return state


def apply(
    charger: AlfenCharger,
    settings: dict[str, Any] | None = None,
    *,
    state: Ocpp | None = None,
    **named: Any,
) -> Ocpp:
    """Write the settings that were named, and return the charger's new state.

    Most of these have no EDS entry, so each write is encoded with the type
    the charger itself reported for that property, falling back to the field
    table's own; ``state`` is the reading that carries those types, and is
    taken fresh when it was not supplied.
    """
    given = {**(settings or {}), **named}
    try:
        checked = fields.values(FIELDS, given)
    except fields.FieldError as exc:
        raise OcppError(str(exc)) from None
    if not checked:
        return read(charger)
    if state is None:
        state = read(charger)
    reported = state.types
    charger.write_properties(
        fields.writes(
            FIELDS,
            checked,
            wire=lambda spec: reported.get(spec.address) or spec.wire,
        )
    )
    return read(charger)


__all__ = [
    "ALL_KEYS",
    "CONNECT_METHODS",
    "FIELDS",
    "Ocpp",
    "OcppError",
    "PROTOCOLS",
    "SECURITY_PROFILES",
    "STATUS_MODES",
    "apply",
    "read",
]
