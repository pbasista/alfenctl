"""Wi-Fi network scanning (the app's *Scan Wi-Fi networks* button).

The charger's SSID (``wifiSSID``, ``328A_0``), passphrase (``wifiPSK``,
``328B_0``, write-only) and security type (``wifiSecurity``, ``328C_0``) are
plain EDS-catalogued properties, already reachable with ``alfenctl get``/
``set``. What is missing is discovery: ``GET /api/wifiscan`` asks the
charger's own radio what networks it can see nearby, so a network can be
picked rather than typed blind (``DlgScanWifiNetworks``).  This module
parses that reply; :meth:`alfenctl.charger.AlfenCharger.wifi_scan` fetches
it.

The security type is a ``SupportedWifiSecurityType`` value -- the same
enumeration as property ``328C_0``'s options, decoded here with labels since
the EDS carries none for it.

**An empty list is not one answer but several.**  The charger can reply with
a document that has no ``scan_results`` at all, with an empty list, or with
entries this parser drops -- a network broadcasting no SSID is one the app
cannot offer either.  Flattening all of that to ``[]`` is how "no networks
found" comes to mean six different things, so :func:`parse_reply` keeps the
distinctions and :func:`parse_scan` is the thin wrapper for callers that only
want the networks.

Field names are matched loosely.  The vendor's own client hands the body to
``JavaScriptSerializer``, which matches members without regard to case, so a
firmware answering ``ssid`` rather than ``Ssid`` would still populate its
dialog; matching exactly here would have printed "no networks found" at it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ICUServiceInstaller.Enums.SupportedWifiSecurityType
SECURITY_LABELS: dict[int, str] = {
    2097154: "WPA-PSK (TKIP)",
    2097156: "WPA-PSK (AES)",
    2097158: "WPA-PSK (AES & TKIP)",
    4194306: "WPA2-PSK (TKIP)",
    4194308: "WPA2-PSK (AES)",
    4194310: "WPA2-PSK (AES & TKIP)",
    6291460: "WPA2/WPA-PSK (AES)",
    6291462: "WPA2/WPA-PSK (AES & TKIP)",
    16777220: "WPA3-PSK (AES)",
    20971524: "WPA3/WPA2-PSK (AES)",
}

# ICUServiceInstaller.Enums.WifiSignalStrength: dBm thresholds, weakest first.
_SIGNAL_BUCKETS: tuple[tuple[int, str], ...] = (
    (-71, "weak"),
    (-61, "fair"),
    (-51, "good"),
)
SIGNAL_EXCELLENT = "excellent"


@dataclass(frozen=True)
class Network:
    """One network the charger's radio can currently see."""

    ssid: str
    signal_dbm: int
    security: int
    band: int | None = None

    @property
    def security_label(self) -> str:
        """A human label for :attr:`security`, or the raw value if unknown."""
        return SECURITY_LABELS.get(self.security, f"unknown (0x{self.security:X})")

    @property
    def signal_label(self) -> str:
        """The app's weak/fair/good/excellent bucket for :attr:`signal_dbm`."""
        for threshold, label in _SIGNAL_BUCKETS:
            if self.signal_dbm < threshold:
                return label
        return SIGNAL_EXCELLENT

    @property
    def supported(self) -> bool:
        """Whether the app would offer connecting to this network at all."""
        return self.security in SECURITY_LABELS


@dataclass(frozen=True)
class ScanReply:
    """What one ``GET /api/wifiscan`` actually said.

    :attr:`networks` is the usable part.  The rest is for saying why that
    part is empty, which is a different sentence each time.
    """

    networks: list[Network] = field(default_factory=list)
    entries: int = 0
    hidden: int = 0
    unusable: int = 0
    complaint: str | None = None

    def summary(self) -> str | None:
        """Say what was dropped or not understood, or None when all was well."""
        if self.complaint:
            return self.complaint
        parts = []
        if self.hidden:
            parts.append(
                f"{self.hidden} network(s) broadcast no SSID and cannot be joined "
                "by name"
            )
        if self.unusable:
            parts.append(f"{self.unusable} entry/entries could not be read")
        return "; ".join(parts) or None


def _field(entry: dict[str, Any], name: str) -> Any:
    """Look a scan field up without insisting on the vendor's capitalisation."""
    wanted = name.replace("_", "").lower()
    for key, value in entry.items():
        if str(key).replace("_", "").lower() == wanted:
            return value
    return None


def _as_int(value: Any) -> int | None:
    """Coerce a scan field to an int, or None when it is not a number."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_reply(body: str) -> ScanReply:
    """Parse a ``GET /api/wifiscan`` reply, keeping what it could not use.

    ``{"scan_results": [...]}`` is the documented shape (``WifiResult``).  A
    body that is not that gets a complaint rather than silence: an empty band
    and an unparsable answer look identical once both are ``[]``.
    """
    text = body.strip()
    if not text:
        return ScanReply(complaint="the charger sent an empty reply")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return ScanReply(complaint=f"the reply was not JSON ({text[:60]!r})")
    if not isinstance(doc, dict):
        return ScanReply(complaint="the reply was not a JSON object")
    entries = doc.get("scan_results")
    if entries is None:
        keys = ", ".join(sorted(map(str, doc))) or "nothing"
        return ScanReply(
            complaint=f"the reply carried no 'scan_results' list (it had: {keys})"
        )
    if not isinstance(entries, list):
        return ScanReply(complaint="'scan_results' was not a list")
    out: list[Network] = []
    hidden = unusable = 0
    for entry in entries:
        if not isinstance(entry, dict):
            unusable += 1
            continue
        ssid = str(_field(entry, "ssid") or "").strip()
        if not ssid:
            hidden += 1
            continue
        signal = _as_int(_field(entry, "signalstrength"))
        if signal is None:
            signal = _as_int(_field(entry, "rssi")) or 0
        band = _as_int(_field(entry, "band"))
        out.append(
            Network(
                ssid=ssid,
                signal_dbm=signal,
                security=_as_int(_field(entry, "security")) or 0,
                band=band,
            )
        )
    # Strongest signal first, like the app's dialog.
    out.sort(key=lambda n: n.signal_dbm, reverse=True)
    return ScanReply(
        networks=out, entries=len(entries), hidden=hidden, unusable=unusable
    )


def parse_scan(body: str) -> list[Network]:
    """Return just the networks in a ``GET /api/wifiscan`` reply."""
    return parse_reply(body).networks
