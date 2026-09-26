"""Where the charger is reachable: Wi-Fi, Ethernet and the modem.

Called connectivity rather than network because this tool has four other
things it could mean.  A charger belongs to a *Smart Charging Network*
(:mod:`alfenctl.scn`); its radio can see Wi-Fi *networks*; its modem picks a
cellular *network*; and it is found by browsing the local *network*.  Only one
of the five is what this module reads, so it is the one that gives the word
up.

``alfenctl wifi`` could already scan for networks and could not join one,
which is the gap this closes.  Joining is three registers written together --
``wifiSSID`` (0x328A), ``wifiPSK`` (0x328B) and ``sysWifiEnabled`` (0x3284) --
and the app writes them from the same dialog its scan feeds
(``DlgScanWifiNetworks`` into ``DlgWifiPassword``).

**The pre-shared key does not read back.**  It is ``rw`` in the EDS and the
charger answers for it, but with a placeholder rather than the key, so nothing
here reports what is currently set: a Wi-Fi password behaves like the
write-only secrets in :mod:`alfenctl.secret` even though it is an ordinary
property.

**A scan needs the radio switched on.**  ``GET /api/wifiscan`` asks the
charger's own radio what it can hear, so with ``sysWifiEnabled`` (0x3284_0)
clear there is nothing to ask and the endpoint answers an empty list almost
at once.  The vendor's installer never explains this either -- it just greys
its *Scan Wi-Fi networks* button out while the flag is clear
(``PanelConnectivity.cs:1521-1532``) -- so :func:`enable` and
:func:`wait_for_radio` are here to make the sequence sayable.

**Addresses come in pairs.**  Each interface's address block stores the live
value in sub 1 and the statically configured one in sub 2 -- ``0x207D_1`` is
the Ethernet address the charger currently has and ``0x207D_2`` the fixed one
it was told to take.  Both vendor sources agree on that layout, and reporting
sub 1 is what answers "where is it right now".

The wired and modem blocks are read-only here on purpose.  Writing an
interface's address over that same interface is how a charger is lost, and
the one command that can stop you reaching a station should not be a flag on
a command whose other flags are harmless; ``alfenctl set 207D_2 …`` remains
for someone who means it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from devicectl import fields
from devicectl.fields import FieldSpec

from alfenctl.charger import AlfenCharger
from alfenctl.eds import INTEGER8, UNSIGNED8, UNSIGNED32, VISIBLE_STRING
from alfenctl.errors import AlfenError

# --- Wi-Fi -------------------------------------------------------------------------------
P_WIFI_ENABLED = (0x3284, 0)  # 12932 sysWifiEnabled
P_WIFI_SSID = (0x328A, 0)  # 12938 wifiSSID
P_WIFI_PSK = (0x328B, 0)  # 12939 wifiPSK -- writable, never readable
P_WIFI_SECURITY = (0x328C, 0)  # 12940 wifiSecurity
P_WIFI_RSSI = (0x328D, 0)  # 12941 wifiRSSI, dBm
P_WIFI_STATUS = (0x328E, 0)  # 12942 wifiStatus
P_WIFI_HARDWARE = (0x328F, 0)  # 12943 wifiHwAvailable
P_WIFI_AP_ENABLED = (0x3291, 0)  # 12945 softAPEnabled
P_WIFI_AP_START = (0x3292, 0)  # 12946 softAPStart
P_WIFI_STATION_STATUS = (0x3293, 0)  # 12947 wifiStationStatus
P_WIFI_AP_STATUS = (0x3294, 0)  # 12948 wifiAPStatus
P_WIFI_ADDRESS = (0x3285, 1)  # 12933 sub 1, the address it has now

# --- Ethernet ----------------------------------------------------------------------------
P_MAC = (0x2052, 1)  # 8274 sub 1, the Ethernet MAC
P_WIRED_ADDRESS = (0x207D, 1)  # 8317 sub 1
P_WIRED_FIXED = (0x207D, 2)  # 8317 sub 2, "use a static address"
P_WIRED_NETMASK = (0x207B, 1)  # 8315 sub 1
P_WIRED_GATEWAY = (0x207C, 1)  # 8316 sub 1
P_WIRED_DNS1 = (0x207E, 1)  # 8318 sub 1
P_WIRED_DNS2 = (0x207F, 1)  # 8319 sub 1

# --- modem -------------------------------------------------------------------------------
P_MOBILE_ADDRESS = (0x2075, 1)  # 8309 sub 1
P_SIGNAL_STRENGTH = (0x2110, 0)  # 8464 gprsSignalStrength
P_IMSI = (0x2104, 0)  # 8452 gprsSIMimsi
P_ICCID = (0x2105, 0)  # 8453 gprsSIMiccid
P_APN = (0x2100, 0)  # 8448 gprsAPNname
P_NETWORK_MODE = (0x2113, 0)  # 8467 automatic or manual
P_NETWORK_TECHNOLOGY = (0x2114, 0)  # 8468 2G/3G/4G

# WifiSecurityType.  The bundled EDS lists exactly these ten and settles a
# disagreement between the two reverse-engineered apps about the last one:
# 20971524 is what the vendor's own catalog says WPA3+WPA2 with AES is.
SECURITY_OPEN = 0
SECURITY_TYPES = {
    SECURITY_OPEN: "open",
    2097154: "WPA PSK (TKIP)",
    2097156: "WPA PSK (AES)",
    2097158: "WPA PSK (AES & TKIP)",
    4194306: "WPA2 PSK (TKIP)",
    4194308: "WPA2 PSK (AES)",
    4194310: "WPA2 PSK (AES & TKIP)",
    6291460: "WPA2/WPA PSK (AES)",
    6291462: "WPA2/WPA PSK (AES & TKIP)",
    16777220: "WPA3 PSK (AES)",
    20971524: "WPA3/WPA2 PSK (AES)",
}

# The default for a network whose scan says it is protected: the widest
# modern mode a charger and a household router will both agree on.
SECURITY_DEFAULT = 4194308

# wifiStatus (0x328E_0), the radio's own state, per the bundled EDS.
WIFI_NOT_INITIALISED = 0
WIFI_RUNNING = 1
WIFI_DISABLED = 2
WIFI_ERROR = 3
WIFI_STATUSES = {
    WIFI_NOT_INITIALISED: "not initialised",
    WIFI_RUNNING: "running",
    WIFI_DISABLED: "disabled",
    WIFI_ERROR: "error",
}

# How long the radio may take to come up after the enable flag is written,
# and how often to ask.  It is an ESP32 booting, not a property being stored.
RADIO_READY_TIMEOUT_S = 20.0
RADIO_POLL_INTERVAL_S = 1.0

STATION_STATUSES = {
    0: "not initialised",
    1: "not configured",
    2: "not connected",
    3: "connected",
}
AP_STATUSES = {0: "not initialised", 1: "disabled", 2: "enabled"}
NETWORK_MODES = {0: "automatic", 1: "manual"}
NETWORK_TECHNOLOGIES = {0: "2G", 1: "3G", 2: "4G"}

# wifiSSID is a 32-byte field, which is also the limit IEEE 802.11 puts on an
# SSID; the PSK is 8..63 characters for WPA-PSK, and empty for an open network.
MAX_SSID = 32
MIN_PSK, MAX_PSK = 8, 63

# The address every commIPaddress register carries until something sets one:
# the EDS DefaultValue shared by 0x2075 (modem), 0x3285 (Wi-Fi) and 0x3296.
# An interface still reporting it has no address of its own, and saying so
# stops two idle interfaces from looking like two interfaces sharing one.
UNSET_ADDRESS = "192.168.000.092"

# sysWifiEnabled is UNSIGNED8 in the bundled EDS; the access-point pair next
# to it is INTEGER8.  Nothing on the wire distinguishes them -- /api/prop
# carries no type -- but the catalog is the catalog.
ENABLED_TYPE = UNSIGNED8


def _address(value: str) -> str:
    """Show an address, marking the factory default for what it is."""
    return f"{value} (unset)" if value.strip() == UNSET_ADDRESS else value


def _wifi_row(value: Any, _state: Connectivity) -> str:
    """Render the radio's enable flag, distinguishing "off" from "did not say".

    A charger that did not answer for the flag is not a charger whose Wi-Fi is
    off; saying "disabled" for both is how an unanswered read gets mistaken
    for a setting.
    """
    if value is None:
        return "not reported"
    return "enabled" if value else "disabled"


def _wired_row(value: Any, state: Connectivity) -> str | None:
    """Render the Ethernet address with how the charger came by it."""
    if not value:
        return None
    return f"{value} ({'static' if state.wired_fixed else 'DHCP'})"


def _address_row(value: Any, _state: Connectivity) -> str | None:
    """Render an interface address, or nothing when there is none."""
    return None if not value else _address(str(value))


def _modem_row(value: Any, _state: Connectivity) -> str:
    """Render the modem's address, which prints even when it has none."""
    return _address(str(value)) if value else "-"


# --- the settings ------------------------------------------------------------------------
# Three tables, because the terminal prints three sections and a station that
# has no radio should not be told its radio is off.  :func:`read` and the web
# document walk all three; :meth:`Connectivity.rows` walks each behind its own
# gate.
#
# Everything here is read-only.  Joining a network is three registers written
# together with a password that never reads back, and writing an interface's
# address over that same interface is how a charger is lost -- so those are
# :func:`connect`, :func:`enable` and ``alfenctl set``, not flags on a table.
WIRED_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        name="mac",
        kind=fields.TEXT,
        address=P_MAC,
        label="Ethernet MAC",
        json="mac",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="wired_address",
        kind=fields.TEXT,
        address=P_WIRED_ADDRESS,
        label="Ethernet address",
        json="wiredAddress",
        access=fields.READ_ONLY,
        render=_wired_row,
    ),
    FieldSpec(
        name="wired_fixed",
        kind=fields.FLAG,
        address=P_WIRED_FIXED,
        json="wiredFixed",
        access=fields.READ_ONLY,
    ),
)

WIFI_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        name="wifi_enabled",
        kind=fields.FLAG,
        address=P_WIFI_ENABLED,
        label="Wi-Fi",
        json="wifiEnabled",
        access=fields.READ_ONLY,
        render=_wifi_row,
    ),
    FieldSpec(
        name="wifi_status",
        kind=fields.ENUM,
        address=P_WIFI_STATUS,
        label="  radio",
        json="wifiStatus",
        options=WIFI_STATUSES,
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="wifi_ssid",
        kind=fields.TEXT,
        address=P_WIFI_SSID,
        label="  network",
        json="wifiSsid",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="wifi_security",
        kind=fields.ENUM,
        address=P_WIFI_SECURITY,
        label="  security",
        json="wifiSecurity",
        options=SECURITY_TYPES,
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="wifi_station_status",
        kind=fields.ENUM,
        address=P_WIFI_STATION_STATUS,
        label="  station",
        json="wifiStationStatus",
        options=STATION_STATUSES,
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="wifi_address",
        kind=fields.TEXT,
        address=P_WIFI_ADDRESS,
        label="  address",
        json="wifiAddress",
        access=fields.READ_ONLY,
        render=_address_row,
    ),
    FieldSpec(
        name="wifi_rssi",
        kind=fields.INTEGER,
        address=P_WIFI_RSSI,
        label="  signal",
        json="wifiRssi",
        unit="dBm",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="wifi_ap_status",
        kind=fields.ENUM,
        address=P_WIFI_AP_STATUS,
        label="  access point",
        json="wifiApStatus",
        options=AP_STATUSES,
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="wifi_hardware",
        kind=fields.FLAG,
        address=P_WIFI_HARDWARE,
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="wifi_ap_enabled",
        kind=fields.FLAG,
        address=P_WIFI_AP_ENABLED,
        json="wifiApEnabled",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="wifi_ap_start",
        kind=fields.FLAG,
        address=P_WIFI_AP_START,
        access=fields.READ_ONLY,
    ),
)

MODEM_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        name="mobile_address",
        kind=fields.TEXT,
        address=P_MOBILE_ADDRESS,
        label="Modem address",
        json="mobileAddress",
        access=fields.READ_ONLY,
        render=_modem_row,
    ),
    FieldSpec(
        name="apn",
        kind=fields.TEXT,
        address=P_APN,
        label="  APN",
        json="apn",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="imsi",
        kind=fields.TEXT,
        address=P_IMSI,
        label="  IMSI",
        json="imsi",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="iccid",
        kind=fields.TEXT,
        address=P_ICCID,
        label="  ICCID",
        json="iccid",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="signal_strength",
        kind=fields.INTEGER,
        address=P_SIGNAL_STRENGTH,
        label="  signal",
        json="signalStrength",
        unit="dBm",
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="network_mode",
        kind=fields.ENUM,
        address=P_NETWORK_MODE,
        label="  mode",
        json="networkMode",
        options=NETWORK_MODES,
        access=fields.READ_ONLY,
    ),
    FieldSpec(
        name="network_technology",
        kind=fields.ENUM,
        address=P_NETWORK_TECHNOLOGY,
        label="  technology",
        json="networkTechnology",
        options=NETWORK_TECHNOLOGIES,
        access=fields.READ_ONLY,
    ),
)

FIELDS: tuple[FieldSpec, ...] = (*WIRED_FIELDS, *WIFI_FIELDS, *MODEM_FIELDS)

# The four Ethernet settings that travel as one block: the charger keeps them
# in four registers and this reports them as one mapping, because a netmask
# without its gateway is not a thing anybody asks for.
WIRED_BLOCK = {
    "netmask": P_WIRED_NETMASK,
    "gateway": P_WIRED_GATEWAY,
    "dns1": P_WIRED_DNS1,
    "dns2": P_WIRED_DNS2,
}
WIRED_BLOCK_LABELS = (
    ("Ethernet netmask", "netmask"),
    ("Ethernet gateway", "gateway"),
    ("Ethernet DNS", "dns1"),
    ("Ethernet DNS 2", "dns2"),
)

ALL_KEYS = (
    *(spec.address for spec in FIELDS if spec.address is not None),
    *WIRED_BLOCK.values(),
)


class ConnectivityError(AlfenError, ValueError):
    """A network setting the charger could not sensibly be given."""


@dataclass
class Connectivity:
    """Where this charger is on the network, per interface."""

    wifi_enabled: bool | None = None
    wifi_ssid: str | None = None
    wifi_security: int | None = None
    wifi_rssi: int | None = None
    wifi_status: int | None = None
    wifi_hardware: bool | None = None
    wifi_station_status: int | None = None
    wifi_ap_enabled: bool | None = None
    wifi_ap_start: bool | None = None
    wifi_ap_status: int | None = None
    wifi_address: str | None = None
    mac: str | None = None
    wired_address: str | None = None
    wired_fixed: bool | None = None
    wired: dict[str, str] = field(default_factory=dict)
    mobile_address: str | None = None
    signal_strength: int | None = None
    imsi: str | None = None
    iccid: str | None = None
    apn: str | None = None
    network_mode: int | None = None
    network_technology: int | None = None

    @property
    def has_wifi(self) -> bool:
        """Whether this charger has a Wi-Fi radio at all."""
        return bool(self.wifi_hardware) or self.wifi_status is not None

    @property
    def radio_ready(self) -> bool:
        """Whether the radio is up, so ``/api/wifiscan`` has something to ask."""
        return self.wifi_status == WIFI_RUNNING

    def scan_obstacle(self) -> str | None:
        """Say why a scan would come back empty, or None when it should work.

        A scan is the radio's own survey.  With the radio off the endpoint
        still answers, and answers nothing, which reads as "no networks in
        range" when it means "nobody was listening".
        """
        if self.wifi_hardware is False:
            return "this charger has no Wi-Fi radio (0x328F_0 is 0)"
        if self.wifi_enabled is False:
            return "the Wi-Fi radio is switched off (sysWifiEnabled, 0x3284_0)"
        if self.wifi_status == WIFI_DISABLED:
            return "the Wi-Fi radio reports itself disabled (wifiStatus, 0x328E_0)"
        if self.wifi_status == WIFI_ERROR:
            return "the Wi-Fi radio reports an error (wifiStatus, 0x328E_0)"
        if self.wifi_status == WIFI_NOT_INITIALISED:
            return "the Wi-Fi radio has not finished starting (wifiStatus, 0x328E_0)"
        return None

    def rows(self) -> list[tuple[str, str]]:
        """Return the label/value pairs worth printing, skipping what is absent.

        Three sections, each behind its own gate: a station with no radio is
        not told its radio is off, and a station with no modem is not given a
        modem row saying it has no address.
        """
        out = fields.rows(WIRED_FIELDS, self)
        for label, key in WIRED_BLOCK_LABELS:
            if self.wired.get(key):
                out.append((label, self.wired[key]))
        if self.has_wifi:
            out.extend(fields.rows(WIFI_FIELDS, self))
        if self.mobile_address or self.imsi or self.apn:
            out.extend(fields.rows(MODEM_FIELDS, self))
        return out


def read(charger: AlfenCharger) -> Connectivity:
    """Read every interface's registers in one ``ids=`` query."""
    live = {lp.key: lp for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}

    def answer(key: tuple[int, int]) -> Any:
        prop = live.get(key)
        return None if prop is None else prop.value

    state = Connectivity(**fields.harvest(FIELDS, answer))
    for name, key in WIRED_BLOCK.items():
        value = answer(key)
        if value not in (None, ""):
            state.wired[name] = str(value)
    return state


def check_credentials(ssid: str, password: str | None, security: int) -> None:
    """Refuse an SSID or a key the radio cannot be given, before sending it."""
    if not ssid or len(ssid) > MAX_SSID:
        raise ConnectivityError(f"an SSID is 1 to {MAX_SSID} characters")
    if security == SECURITY_OPEN:
        if password:
            raise ConnectivityError("an open network takes no password")
        return
    if not password:
        raise ConnectivityError("this security type needs a password")
    if not MIN_PSK <= len(password) <= MAX_PSK:
        raise ConnectivityError(f"a WPA password is {MIN_PSK} to {MAX_PSK} characters")


def connect(
    charger: AlfenCharger,
    ssid: str,
    password: str | None = None,
    *,
    security: int | None = None,
) -> Connectivity:
    """Join a Wi-Fi network: SSID, key and the enable flag in one write.

    ``security`` defaults to WPA2-AES when a password was given and to open
    when one was not, which is the pair the app's own scan dialog offers.
    """
    if security is None:
        security = SECURITY_DEFAULT if password else SECURITY_OPEN
    if security not in SECURITY_TYPES:
        raise ConnectivityError(f"unknown Wi-Fi security type {security}")
    check_credentials(ssid, password, security)
    writes: dict[tuple[int, int], tuple[Any, int | None]] = {
        P_WIFI_SSID: (ssid, VISIBLE_STRING),
        P_WIFI_SECURITY: (security, UNSIGNED32),
        P_WIFI_ENABLED: (1, ENABLED_TYPE),
    }
    if security != SECURITY_OPEN and password is not None:
        writes[P_WIFI_PSK] = (password, VISIBLE_STRING)
    charger.write_properties(writes)
    return read(charger)


def enable(charger: AlfenCharger) -> Connectivity:
    """Switch the Wi-Fi radio on, leaving the stored network alone.

    This is what has to happen before a scan: the radio is the thing doing
    the scanning.  It takes effect without a reboot -- 0x3284_0 is not one of
    the ids My Eve lists as needing one -- but the radio still takes a few
    seconds to come up, which is what :func:`wait_for_radio` is for.
    """
    charger.write_properties({P_WIFI_ENABLED: (1, ENABLED_TYPE)})
    return read(charger)


def disconnect(charger: AlfenCharger) -> Connectivity:
    """Switch the Wi-Fi radio off, leaving the stored network alone."""
    charger.write_properties({P_WIFI_ENABLED: (0, ENABLED_TYPE)})
    return read(charger)


def wait_for_radio(
    charger: AlfenCharger,
    *,
    timeout: float | None = None,
    interval: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Connectivity:
    """Poll ``wifiStatus`` until the radio is running, or the patience runs out.

    Returns the last reading either way; the caller decides what an unready
    radio means.  The two limits are read from the module rather than bound
    as defaults so a test can shorten them; ``sleep`` is the other seam.
    """
    timeout = RADIO_READY_TIMEOUT_S if timeout is None else timeout
    interval = RADIO_POLL_INTERVAL_S if interval is None else interval
    deadline = time.monotonic() + timeout
    state = read(charger)
    while not state.radio_ready and time.monotonic() < deadline:
        sleep(interval)
        state = read(charger)
    return state


def set_access_point(
    charger: AlfenCharger, *, enabled: bool | None = None, start: bool | None = None
) -> Connectivity:
    """Turn the charger's own access point on or off."""
    writes: dict[tuple[int, int], tuple[Any, int | None]] = {}
    if enabled is not None:
        writes[P_WIFI_AP_ENABLED] = (int(enabled), INTEGER8)
    if start is not None:
        writes[P_WIFI_AP_START] = (int(start), INTEGER8)
    if writes:
        charger.write_properties(writes)
    return read(charger)


__all__ = [
    "ALL_KEYS",
    "Connectivity",
    "ConnectivityError",
    "SECURITY_TYPES",
    "connect",
    "disconnect",
    "enable",
    "read",
    "set_access_point",
    "wait_for_radio",
]
