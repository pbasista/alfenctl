"""mDNS discovery of Alfen chargers on the local network.

The Windows app has no cloud "list my stations" endpoint; it finds chargers
purely by mDNS, browsing two service types (``ICUNetwork.LANConnection.
serviceTypes``):

* ``_alfen._tcp`` -- the new generation (v5+ / AHP), served over HTTPS;
* ``_lolo3._http._tcp`` -- the old generation (NG9xx < 5.0), served over HTTP.

So "the stations associated with your credentials" means: the chargers
reachable on your LAN that your credentials can log into. ``--host`` targets
one directly (the app's "manual IP" connection).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

# Seconds to browse before reporting what was found (the app browses continuously).
DEFAULT_DISCOVER_TIME_S = 4.0
# Timeout passed to zeroconf when resolving a discovered service (milliseconds).
MDNS_RESOLVE_TIMEOUT_MS = 3000

# mDNS service types the app browses for.
MDNS_SERVICES = ("_alfen._tcp.local.", "_lolo3._http._tcp.local.")
# The ``_alfen._tcp`` service type marks the new (v5+, HTTPS) generation.
MDNS_NEWGEN_PREFIX = "_alfen"

DEFAULT_HTTPS_PORT = 443
DEFAULT_HTTP_PORT = 80


@dataclass
class Station:
    """A discovered (or manually specified) charger, before we log in."""

    ip: str
    port: int
    hostname: str = ""
    https: bool = True

    @property
    def object_id(self) -> str:
        """Return the Object ID / serial (the hostname's last '-' segment, as the app does)."""
        base = self.hostname.split(".")[0]
        return base.rsplit("-", 1)[-1] if "-" in base else base


class _Collector(ServiceListener):
    """Zeroconf listener that collects discovered Alfen chargers into a dict."""

    def __init__(self) -> None:
        """Initialise the empty collection keyed by object id (or IP)."""
        self.found: dict[str, Station] = {}

    def _add(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Resolve a discovered service and record it as a :class:`Station`."""
        info = zc.get_service_info(type_, name, timeout=MDNS_RESOLVE_TIMEOUT_MS)
        if not info or not info.parsed_addresses():
            return
        ip = info.parsed_addresses()[0]
        is_newgen = type_.startswith(MDNS_NEWGEN_PREFIX)
        st = Station(
            ip=ip,
            port=info.port or (DEFAULT_HTTPS_PORT if is_newgen else DEFAULT_HTTP_PORT),
            hostname=info.server or name,
            https=is_newgen,
        )
        self.found[st.object_id or ip] = st

    add_service = _add
    update_service = _add

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Ignore service removals; we only ever collect."""


def discover(duration: float = DEFAULT_DISCOVER_TIME_S) -> list[Station]:
    """Browse the LAN for Alfen chargers for ``duration`` seconds.

    Return the stations sorted by Object ID. (The app browses continuously.)
    """
    zc = Zeroconf()
    listener = _Collector()
    browsers = [ServiceBrowser(zc, svc, listener) for svc in MDNS_SERVICES]
    try:
        time.sleep(duration)
    finally:
        for b in browsers:
            b.cancel()
        zc.close()
    return sorted(listener.found.values(), key=lambda s: s.object_id)
