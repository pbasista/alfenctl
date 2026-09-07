"""The charger-local HTTP API client (the app's ``ICUNetwork.ICULanDevice``).

Everything after mDNS discovery talks to the charger's local HTTP API at
``{http|https}://{ip}:{port}/api/{command}``, JSON in and out. Two protocol
generations exist:

* old (NG9xx < 5.0, mDNS ``_lolo3``, plain HTTP): cookie session plus HTTP
  Basic ``user:pass`` on every request;
* new (v5+ / AHP, mDNS ``_alfen``, HTTPS with a self-signed certificate):
  session established by ``POST /api/login`` -- the newest firmware answers
  with a JSON token pair, others (like the tested NG910) with an empty body
  plus a session cookie.

Session handling notes, all confirmed against a live NG910 (fw 7.4.5):

* The session is bound to the TCP connection: requests must reuse one
  keep-alive connection, and the charger serves only ONE connection at a time
  (hence the dedicated fresh connection for the firmware upload).
* The session lapses after a short idle, so :meth:`AlfenCharger._authed`
  re-logs-in and retries once on 401/403, like the app's
  ``HandleUnsuccessfulRequest``.

The firmware upload (:meth:`AlfenCharger.upload_firmware`) has four
non-obvious requirements, each isolated on the live charger:

* Stream the body in small (<= :data:`UPLOAD_WRITE_SIZE`) pieces. One large
  write produces ~16 KB TLS records and the charger resets within ~1 s; a
  request stream that yields <= 7 KB pieces (:class:`_FixedChunkStream`)
  makes httpcore emit one <= 7 KB TLS record per piece, so plain httpx works
  with no raw socket. ``Content-Length`` is set by hand (no chunked encoding).
* Send the image as ONE multipart part. The charger accepts a single
  hand-built part but rejects (HTTP 400) httpx's native ``files=`` multipart,
  whose per-part ``Content-Type`` the app's .NET output omits. So single-part
  is about *acceptance*, not transport.
* Send ``Accept: */*``, never ``Accept: application/json``. The firmware
  endpoint resets the connection ~0.2 s in for a POST that asks for a JSON
  response, so the upload overrides the client's JSON default on this one
  request.
* Read only the response status line (``stream=True``): the charger normally
  returns HTTP 200, but should it drop the connection while rebooting to apply
  the image, a drop after the FULL body was delivered still counts as success.
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from alfenctl.discovery import Station
from alfenctl.eds import (
    ARRAY_16,
    BOOLEAN,
    BYTEARRAY,
    DOMAIN,
    OCTET_STRING,
    REAL32,
    REAL64,
    UNICODE_STRING,
    UNSIGNED64,
    VISIBLE_STRING,
)
from alfenctl.errors import AlfenError
from alfenctl.firmware import (
    FW_NO_ACTIVE_UPDATE,
    device_family,
    parse_fw_version,
)
from alfenctl.progress import BYTES_PER_MB, PROGRESS_DEBUG_STEP, fmt_duration

# --- HTTP status codes we branch on -----------------------------------------------------

HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403

# --- Network defaults --------------------------------------------------------------------

# Per-request timeout for the small JSON API calls made over httpx.
DEFAULT_HTTP_TIMEOUT_S = 30.0
# TCP/TLS connect timeout for the httpx client.
CONNECT_TIMEOUT_S = 10.0
# Read/write timeout for the (slow) firmware upload; the charger takes
# ~45-65 s per 1.8 MB.
UPLOAD_TIMEOUT_S = 300.0
# Timeout for a poll issued while the charger is installing and rebooting.
# Its web server is either up and answers in well under a second, or it is
# down -- there is nothing to wait 30 s for, and a poll that blocks that long
# stalls the progress display.
REBOOT_POLL_TIMEOUT_S = 4.0
# Clearing the whitelist walks the charger's flash; the app gives it 10 s.
WHITELIST_CLEAR_TIMEOUT_S = 10.0
# A Wi-Fi scan takes a moment on the charger's radio (ExecutedWifiScan).
WIFI_SCAN_TIMEOUT_S = 11.0
# Pause after dropping the API connection so the charger frees its single
# connection slot before the upload's fresh connection logs in.
CONNECTION_RELEASE_PAUSE_S = 0.5
# The charger resets the connection on TLS records larger than ~8 KB, so the
# upload request stream yields at most this many bytes per chunk (httpcore
# writes one TLS record per chunk).
UPLOAD_WRITE_SIZE = 7000

# --- Login -------------------------------------------------------------------------------

# Default charger login used by the old (pre-5.0, HTTP) firmware when no other
# creds are supplied (ICUNetworkConfig.HTTPUsernameOld / HTTPPasswordOld).
DEFAULT_OLD_USER, DEFAULT_OLD_PASSWORD = "cpadmin", "L@0Pa$$"
# Display name we send with every login (arbitrary; the app sends the
# engineer's name).
LOGIN_DISPLAY_NAME = "alfen_installer"

# --- Property pagination ------------------------------------------------------------------

# ``limit`` requested per api/prop page.
PROP_PAGE_SIZE = 500
# Hard safety cap so a charger that ignores the paging params can't spin us in
# an infinite loop.
MAX_PROP_PAGES = 1000
# The charger marks read-only properties with access 1 in /api/prop replies
# (ICULanDevice.ParseProperty: ``num == 1`` -> ReadOnly).
ACCESS_READ_ONLY = 1
# The app writes properties in batches of at most 15 (StoreProperties).
STORE_BATCH_SIZE = 15
# How many ids go into one ``ids=`` read (the app joins them comma-separated;
# batching only keeps the request URL short).
IDS_QUERY_BATCH = 25

# --- Property object IDs (CANopen-style) --------------------------------------------------

# The charger's "id" is "<propId hex>_<subId hex>" with NO fixed width (e.g.
# "100A_0"), so we key properties by a parsed numeric (propId, subId) tuple,
# like the app does.
# 4104 manufacturer device name (e.g. "NG910"), used as a model fallback.
P_DEVICE_NAME = (0x1008, 0)
P_SW_VERSION = (0x100A, 0)  # 4106 software version, e.g. "5.6.1-4183"
# 8272 sysChargePointModel (AHP*/AHWP* => AHP family, else NG/Eve/Twin/Tube).
P_MODEL = (0x2050, 0)
P_SERIAL = (0x2051, 0)  # 8273 sysChargePointSerialNumber / Object ID
P_IDENTITY = (0x2053, 0)  # 8275 sysChargeBoxIdentity
P_NR_SOCKETS = (0x205E, 0)  # 8286 number of sockets
P_DATE_TIME = (0x2059, 0)  # 8281 sysDateTime, ms since the Unix epoch (UTC)

# A property id splits into exactly two parts: the object id and the sub-index.
PROP_ID_PARTS = 2

# The clock command carries whole seconds and is applied when it arrives, so
# it is aimed at half a round trip ahead -- the usual estimate of the one-way
# delay.  Capped, so one slow response cannot throw the clock forwards.
MAX_CLOCK_LEAD_S = 2.0


def _timeout_kwargs(timeout: float | None) -> dict[str, Any]:
    """Return httpx request kwargs overriding the timeout, or nothing at all.

    The connect timeout is capped at the override too: a charger that is
    down usually shows up as a connect that never completes.
    """
    if timeout is None:
        return {}
    return {"timeout": httpx.Timeout(timeout, connect=min(timeout, CONNECT_TIMEOUT_S))}


# --- Debug logging -------------------------------------------------------------------------

# Characters of a response body to show in debug output.
RESPONSE_PREVIEW_CHARS = 200

# JSON keys whose value never reaches debug output: the login and end-user
# passwords, and the recovery code printed on the charger, which resets the
# password to its default (:meth:`Charger.reset_password`).
SECRET_JSON_KEY_RE = re.compile(r'("(?:password|code)"\s*:\s*)".*?"')


class UploadError(AlfenError):
    """The firmware upload failed at the transport level or was rejected."""


def parse_prop_id(raw: str) -> tuple[int, int] | None:
    """Parse a property id like "100A_0" or "205E_00" into ``(0x100A, 0)``.

    Return ``None`` if the id is not in that ``hex_hex`` form.
    """
    parts = raw.split("_")
    if len(parts) != PROP_ID_PARTS:
        return None
    try:
        return int(parts[0], 16), int(parts[1], 16)
    except ValueError:
        return None


def _sockets_from_type(raw: object) -> int | None:
    """Read the socket count out of /api/info's ``Type`` field.

    The field is a three-part version string whose first component is the
    number of sockets: My Eve's own fixtures give ``"1.0.1"`` for a single
    socket and ``"2.0.1"`` for the double-socket station
    (decompiled.js:818125-818152).
    """
    head = str(raw or "").split(".")[0].strip()
    return int(head) if head.isdigit() else None


@dataclass
class ChargerInfo:
    """A few identifying properties of a charger, like the app's Information panel."""

    object_id: str
    identity: str | None
    model: str | None
    family: str
    firmware: str
    firmware_version: tuple[int, int, int] | None
    sockets: int | None


@dataclass
class LiveProperty:
    """One property as reported live by the charger's ``GET /api/prop``.

    The charger supplies the value plus its own metadata: ``type`` (an SDT
    code), ``access`` (1 == read-only), ``len`` and ``cat``.  Names, titles
    and enumerations are not on the wire -- they come from the EDS catalog.
    """

    id: str
    key: tuple[int, int]
    value: Any
    data_type: int | None = None
    access: int | None = None
    length: int | None = None
    category: str | None = None

    @property
    def writable(self) -> bool:
        """Whether the charger allows writing (read-only is marked access 1)."""
        return self.access != ACCESS_READ_ONLY


def parse_live_property(entry: dict[str, Any]) -> LiveProperty | None:
    """Parse one ``properties`` array entry from an ``/api/prop`` reply.

    Returns None when the id does not parse (the app likewise skips those
    in ``ParseProperty``).
    """

    def int_field(name: str) -> int | None:
        raw = entry.get(name)
        return raw if isinstance(raw, int) and not isinstance(raw, bool) else None

    key = parse_prop_id(str(entry.get("id", "")))
    if key is None:
        return None
    category = entry.get("cat")
    return LiveProperty(
        id=str(entry.get("id", "")),
        key=key,
        value=entry.get("value"),
        data_type=int_field("type"),
        access=int_field("access"),
        length=int_field("len"),
        category=category if isinstance(category, str) else None,
    )


def encode_property_value(data_type: int | None, value: Any) -> Any:
    """Encode a typed value as the charger expects it in a POST /api/prop body.

    Mirrors ``ICULanDevice.StoreProperties``: strings/booleans/byte arrays
    travel as JSON strings (booleans in C# ``ToString`` casing; byte arrays
    as comma-joined hex), reals and integers as raw JSON numbers.  An unknown
    type passes the value through unchanged.
    """
    if value is None:
        return None
    if data_type == BYTEARRAY:
        if isinstance(value, str):  # tolerate "0A,FF"-style strings
            return ",".join(
                f"{int(part, 16):02X}" for part in value.split(",") if part.strip()
            )
        return ",".join(f"{b:02X}" for b in value)
    if data_type == ARRAY_16:
        if isinstance(value, str):
            return ",".join(
                f"{int(part, 16):04X}" for part in value.split(",") if part.strip()
            )
        return ",".join(f"{int(v):04X}" for v in value)
    if data_type == BOOLEAN:
        return ("True" if value else "False") if isinstance(value, bool) else str(value)
    if data_type in (VISIBLE_STRING, UNICODE_STRING, OCTET_STRING, DOMAIN):
        return str(value)
    if data_type in (REAL32, REAL64):
        return float(value)
    if data_type is not None:  # the integer family
        return int(value)
    return value


class _FixedChunkStream(httpx.SyncByteStream):
    """A fixed request body handed to httpx as a stream, yielded in small pieces.

    httpcore performs one socket write (hence one TLS record) per yielded
    chunk, so capping the chunk at :data:`UPLOAD_WRITE_SIZE` keeps every record
    under the charger's ~8 KB reset threshold. Because we pass this as the
    request ``stream`` and set ``Content-Length`` ourselves, httpx adds no
    ``Transfer-Encoding: chunked``; the charger sees a normal, framed request
    that merely arrives in small records. :attr:`sent` tracks bytes yielded so
    the caller can tell a full-body-then-reboot drop from an early transport
    failure, and ``on_progress`` (if given) is called with that running total
    for a progress bar. See :meth:`AlfenCharger.upload_firmware`.
    """

    def __init__(
        self,
        body: bytes,
        chunk: int = UPLOAD_WRITE_SIZE,
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        """Wrap ``body``, to be yielded in ``chunk``-byte pieces."""
        self._body = body
        self._chunk = chunk
        self._on_progress = on_progress
        self.sent = 0

    def __iter__(self) -> Iterator[bytes]:
        """Yield the body in ``chunk``-byte pieces, counting bytes handed to httpcore."""
        self.sent = 0
        for i in range(0, len(self._body), self._chunk):
            piece = self._body[i : i + self._chunk]
            self.sent += len(piece)
            if self._on_progress is not None:
                self._on_progress(self.sent)
            yield piece

    def close(self) -> None:
        """No resources to release (the body is an in-memory bytes object)."""


class AlfenCharger:
    """Client for the charger-local API, matching ``ICULetwork.ICULanDevice``.

    Pass ``transport`` to substitute the HTTP transport -- httpx's
    ``MockTransport`` is used by the test suite to exercise the client without
    a charger.
    """

    def __init__(
        self,
        station: Station,
        username: str,
        password: str,
        *,
        timeout: float = DEFAULT_HTTP_TIMEOUT_S,
        debug: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Set up the client for ``station`` with the given credentials."""
        self.station = station
        self.username = username
        self.password = password
        self.https = station.https
        self.debug = debug
        self._token: str | None = None
        # Set to follow an upload's progress as (sent, total, elapsed_s).
        # A slow upload is otherwise silent: this module does not draw, it
        # reports (alfenctl.report.Reporter.sending is what gets hooked up).
        self.on_upload_progress: Callable[[int, int, float], None] | None = None
        self._timeout = timeout
        self._transport = transport
        self._base = (
            f"{'https' if self.https else 'http'}://{station.ip}:{station.port}"
        )
        # The charger uses a self-signed cert; the app bypasses validation
        # (ICULanDevice.ValidateServerCertificate).
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        self._c = self._make_client()

    def _make_client(self) -> httpx.Client:
        """Build the httpx client used for the (small) JSON API calls.

        This charger binds the login session to the TCP connection, so we must
        REUSE one connection across requests (keep-alive): a fresh connection
        per request (``Connection: close``) makes every call after login
        return 401. httpx reuses a pooled connection for sequential same-host
        requests by default; ``max_connections=1`` also matches the app's
        single-connection behaviour, and this charger accepts only ONE
        connection at a time, which is why the upload opens a fresh connection
        via :meth:`_reset_connection` first.
        """
        auth = None if self.https else httpx.BasicAuth(self.username, self.password)
        hooks = (
            {"request": [self._log_request], "response": [self._log_response]}
            if self.debug
            else {}
        )
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        return httpx.Client(
            base_url=self._base,
            verify=self._ctx,
            auth=auth,
            limits=limits,
            timeout=httpx.Timeout(self._timeout, connect=CONNECT_TIMEOUT_S),
            headers={"Accept": "application/json"},
            event_hooks=hooks,
            transport=self._transport,
        )

    def _reset_connection(self) -> None:
        """Close the API connection and rebuild a fresh, logged-out client.

        The session is bound to the TCP connection and the charger serves only
        ONE connection at a time, so the upload gets its own connection (the
        caller logs in again on it): this keeps the ~60 s streaming upload
        self-contained and off the short-request API client.
        """
        self._c.close()
        self._token = None
        self._c = self._make_client()
        # Give the charger a moment to free its single connection slot.
        time.sleep(CONNECTION_RELEASE_PAUSE_S)

    # -- debug logging --------------------------------------------------------------------
    @staticmethod
    def _log_request(req: httpx.Request) -> None:
        """Log an outgoing request to stderr, redacting secrets in the body."""
        is_json = req.headers.get("content-type", "").startswith("application/json")
        body = req.content if is_json else b""
        text = SECRET_JSON_KEY_RE.sub(r'\1"***"', body.decode("utf-8", "replace"))
        extra = f"  body={text}" if body else ""
        print(f"[debug] >> {req.method} {req.url}{extra}", file=sys.stderr)
        # For non-JSON requests (i.e. the firmware upload) show the interesting headers.
        if not is_json:
            interesting = {
                k: v
                for k, v in req.headers.items()
                if k.lower()
                in ("content-type", "content-length", "expect", "connection")
            }
            print(f"[debug]      headers={interesting}", file=sys.stderr)

    @staticmethod
    def _log_response(resp: httpx.Response) -> None:
        """Log an incoming response (status, size, selected headers, and a body preview)."""
        resp.read()  # materialize the body so we can size/preview it
        preview = resp.text[:RESPONSE_PREVIEW_CHARS].replace("\n", " ")
        hdrs = {
            k: v
            for k, v in resp.headers.items()
            if k.lower()
            in (
                "connection",
                "content-length",
                "content-type",
                "www-authenticate",
                "keep-alive",
            )
        }
        print(
            f"[debug] << {resp.status_code} {resp.reason_phrase} "
            f"({len(resp.content)} bytes) hdrs={hdrs} {preview}",
            file=sys.stderr,
        )

    # -- low level ------------------------------------------------------------------------
    def _url(self, command: str) -> str:
        """Return the API path for ``command`` (e.g. "login" -> "/api/login")."""
        return f"/api/{command}"

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._c.close()

    def __enter__(self) -> "AlfenCharger":
        """Enter the context manager, returning self."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Exit the context manager, closing the client."""
        self.close()

    # -- auth -----------------------------------------------------------------------------
    def login(self, timeout: float | None = None) -> None:
        """Establish a session, tolerating both charger generations.

        The newest firmware returns a JSON token pair ``{"access", "refresh"}``,
        which we carry as a Bearer header; older firmware returns an empty body
        plus a session cookie, which httpx persists automatically. (HTTP
        chargers additionally carry the Basic-auth header set on the client.)
        """
        body = {
            "username": self.username,
            "password": self.password,
            "displayname": LOGIN_DISPLAY_NAME,
        }
        r = self._c.post(self._url("login"), json=body, **_timeout_kwargs(timeout))
        r.raise_for_status()
        self._token = None
        if r.content.strip():  # token-based firmware returns a JSON body
            try:
                self._token = r.json().get("access")
            except json.JSONDecodeError:
                pass
        if self._token:
            self._c.headers["Authorization"] = f"Bearer {self._token}"
        else:
            # Cookie-session firmware: rely on the cookie, carry no bearer header.
            self._c.headers.pop("Authorization", None)

    def logout(self) -> None:
        """Best-effort logout; ignore any transport or closed-client error."""
        try:
            self._c.post(self._url("logout"), json="")
        except (httpx.HTTPError, RuntimeError):
            pass

    def _authed(
        self,
        method: str,
        command: str,
        *,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an authenticated request, re-logging-in once on 401/403 and retrying.

        The charger drops the session after a short idle (e.g. while the user
        sits at the upgrade prompt) and, because the session is bound to the
        TCP connection, across its own reboot. Mirrors
        ``ICULanDevice.HandleUnsuccessfulRequest``, which re-logs-in and
        retries on Unauthorized/Forbidden.

        ``timeout`` overrides the client's per-request timeout for the call
        *and* for the re-login it may trigger, so a caller working to a
        budget (the reboot poll) cannot be held past it by the retry.
        """
        limit = _timeout_kwargs(timeout)
        r = self._c.request(method, self._url(command), **limit, **kwargs)
        if r.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
            if self.debug:
                print(
                    f"[debug] -- {r.status_code} on {command}; re-authenticating and retrying",
                    file=sys.stderr,
                )
            self.login(timeout=timeout)
            r = self._c.request(method, self._url(command), **limit, **kwargs)
        r.raise_for_status()
        return r

    # -- properties -----------------------------------------------------------------------
    def categories(self) -> list[str]:
        """Return the property category names from GET /api/categories."""
        r = self._authed("GET", "categories")
        return [str(c).strip('" ') for c in r.json().get("categories", [])]

    def fetch_log(self, offset: int = 0, lines: int | None = None) -> str:
        """Return raw charger event-log text from GET /api/log (one page).

        ``offset`` counts lines back from the newest one, so ``offset=0`` is
        the newest page and each further page steps into the past.  Mirrors
        ``ICULanDevice.GetLogLines``: parameter order is ``offset=N``, plus
        ``&lines=M`` -- which the app sends to AHP >= 2.4 only, and not on
        the first page.  Lines are ``id_<ISO8601>:TYPE:source:line:text``;
        :mod:`alfenctl.logs` parses and pages them.
        """
        query = f"offset={offset}"
        if lines is not None and offset != 0:
            query += f"&lines={lines}"
        r = self._authed("GET", f"log?{query}")
        return r.text

    def fetch_transactions(self, offset: int = 0xFFFFFFFF) -> str:
        """Return one page of the transaction database from GET /api/transactions.

        Mirrors ``ICUTransactions.Read``: ``offset`` is a record offset and
        paging runs backwards from ``0xFFFFFFFF`` ("the newest"), each page
        answered with the offset to ask for next.  The body is text, not
        JSON; :mod:`alfenctl.transactions` parses it.
        """
        r = self._authed("GET", f"transactions?offset={offset}")
        return r.text

    def fetch_whitelist(self, index: int = 0) -> str:
        """Return one page of the RFID whitelist from GET /api/whitelist.

        ``index`` is a position in a *sparse* list, so an empty page is not
        the end of it; :mod:`alfenctl.whitelist` does the walking.
        """
        r = self._authed("GET", f"whitelist?index={index}")
        return r.text

    def whitelist_verb(self, query: str) -> None:
        """Send a whitelist action: ``add=<tag>``, ``remove=<tag>``, ``clear``, ...

        These are query strings on the same endpoint, not a body
        (``ICUWhiteList``).  ``clear`` walks the charger's flash, so it gets
        the app's longer timeout.
        """
        timeout = WHITELIST_CLEAR_TIMEOUT_S if query == "clear" else None
        self._authed("GET", f"whitelist?{query}", timeout=timeout)

    def add_tag(self, record: Mapping[str, Any]) -> None:
        """Write one whole whitelist record (``POST /api/addtag``)."""
        self._authed("POST", "addtag", json=dict(record))

    def fetch_charging_profile_ids(self) -> httpx.Response:
        """``GET /api/chargingprofiles?id_list`` -- also how support is probed.

        Mirrors ``ICUChargingProfiles.SupportsChargingProfiles``/
        ``GetAllChargingProfileIds``: the endpoint answers 404 (raised as
        :class:`httpx.HTTPStatusError`) on firmware that does not implement
        it at all.
        """
        return self._authed("GET", "chargingprofiles?id_list")

    def fetch_charging_profile(self, profile_id: int) -> httpx.Response:
        """``GET /api/chargingprofiles?cpid=<id>`` -- one profile's schedule."""
        return self._authed("GET", f"chargingprofiles?cpid={profile_id}")

    def clear_charging_profile(self, profile_id: int | str) -> None:
        """Remove one profile, or every profile with ``"all"`` (``Clear``/``ClearAll``).

        A POST with an empty body, like the app (``content=""`` is not
        ``null`` in ``ExecuteWebRequest``, which is what selects POST).
        """
        self._authed("POST", f"chargingprofiles?clear={profile_id}", content=b"")

    def add_charging_profile(self, profile: Mapping[str, Any]) -> httpx.Response:
        """``POST /api/chargingprofiles?add=`` with one profile as the JSON body.

        ``profile`` is the whole ``{"connectorId": ..., "csChargingProfiles":
        {...}}`` document; :mod:`alfenctl.charging_profiles` builds it.
        """
        return self._authed("POST", "chargingprofiles?add=", json=dict(profile))

    def wifi_scan(self) -> str:
        """Return raw JSON from ``GET /api/wifiscan`` (nearby networks).

        Mirrors ``ICULanDevice.ExecutedWifiScan``: a plain GET (no query,
        no body), given the app's longer 11 s timeout -- a scan takes a
        moment on the charger's radio. :mod:`alfenctl.wifi` parses the
        result.
        """
        r = self._authed("GET", "wifiscan", timeout=WIFI_SCAN_TIMEOUT_S)
        return r.text

    def erase_transactions(self, is_ahp: bool = False) -> None:
        """Erase the transaction database (``EraseTransactionDatabase``).

        NG chargers take the ``txerase`` console command; AHP has a
        database-reset endpoint instead.
        """
        if is_ahp:
            self._authed("POST", "db/reset?dbname=transactions", content=b"")
        else:
            self.send_command("txerase")

    @staticmethod
    def _parse_prop_doc(doc: Any) -> list[LiveProperty]:
        """Parse an ``/api/prop`` document into live properties.

        Two shapes occur: the paged ``{"properties": [...]}`` list, and a
        flat ``{"<id>": <value>}`` map for ``ids=`` reads on some firmware
        (the app's ``ParseProperty`` default branch).  Non-property keys
        ("version", "total", ...) don't parse as ids and drop out.
        """
        if isinstance(doc, dict):
            props = doc.get("properties")
            if isinstance(props, list):
                return [lp for lp in map(parse_live_property, props) if lp]
            out: list[LiveProperty] = []
            for raw_id, value in doc.items():
                key = parse_prop_id(str(raw_id))
                if key is not None and not isinstance(value, (dict, bool)):
                    out.append(LiveProperty(id=str(raw_id), key=key, value=value))
            return out
        return []

    def fetch_properties(self, category: str | None = None) -> list[LiveProperty]:
        """Fetch live properties, paginated (one category, or all of them).

        ``category=None`` sends no ``cat`` filter -- the AHP firmware >= 2.2
        shape -- which returns every property.  The query string is built
        by hand in the app's parameter order (``cat``, ``limit``,
        ``offset``; ICULanDevice.UpdatePropertiesInternal builds
        ``"cat=<c>&limit=500"`` and appends ``&offset=N``): the charger's
        embedded server matches the query prefix literally and returns an
        empty page when ``limit`` comes first.  We advance a strictly
        monotonic local offset (not the server-echoed one) and stop on a
        short page, so a charger that ignores the paging params can't spin
        us in an infinite loop.
        """
        out: dict[tuple[int, int], LiveProperty] = {}
        query = f"cat={category}&" if category is not None else ""
        query += f"limit={PROP_PAGE_SIZE}"
        offset = 0
        for _ in range(MAX_PROP_PAGES):
            r = self._authed("GET", f"prop?{query}&offset={offset}")
            doc = r.json() if isinstance(r.json(), dict) else {}
            props = self._parse_prop_doc(doc)
            for lp in props:
                out[lp.key] = lp
            total = doc.get("total")
            offset += len(props)
            if not props or len(props) < PROP_PAGE_SIZE:
                break
            if total is not None and offset >= total:
                break
        return list(out.values())

    def fetch_properties_by_ids(
        self, keys: Sequence[tuple[int, int]]
    ) -> list[LiveProperty]:
        """Fetch specific properties by id, like the app's ``ids=`` reads.

        Ids are batched to keep the request URL short; each reply may use
        either document shape.
        """
        out: list[LiveProperty] = []
        for start in range(0, len(keys), IDS_QUERY_BATCH):
            batch = keys[start : start + IDS_QUERY_BATCH]
            ids = ",".join(f"{p:X}_{s:X}" for p, s in batch)
            # Build the query string by hand: passing `params=` percent-encodes
            # the comma (%2C) and the charger does not decode it, so it sees a
            # single bogus id and returns nothing. The app joins the ids into
            # the URI verbatim, too.
            r = self._authed("GET", f"prop?ids={ids}")
            out.extend(self._parse_prop_doc(r.json()))
        return out

    def all_properties(
        self, on_category: Callable[[int, int, str], None] | None = None
    ) -> list[LiveProperty]:
        """Fetch every live property, like the app's UpdateCategories loop.

        Categories come from ``GET /api/categories``; an empty reply falls
        back to one unfiltered paged read (the AHP >= 2.2 shape).  Duplicate
        ids across categories keep their last value.

        ``on_category(done, total, name)`` is called after each category, if
        given.  A walk of the whole charger is the slowest read there is --
        it is what a backup costs -- and this is the one long read that
        knows in advance how many steps it has, so whoever is drawing a
        progress bar for it can draw a real one.
        """
        sources: list[LiveProperty] = []
        cats = self.categories()
        if cats:
            for index, cat in enumerate(cats):
                sources.extend(self.fetch_properties(cat))
                if on_category is not None:
                    on_category(index + 1, len(cats), cat)
        else:
            sources.extend(self.fetch_properties(None))
            if on_category is not None:
                on_category(1, 1, "")

        seen: dict[tuple[int, int], LiveProperty] = {}
        for lp in sources:
            seen[lp.key] = lp
        return list(seen.values())

    def properties(self, category: str = "generic") -> dict[tuple[int, int], Any]:
        """Return ``{(propId, subId): value}`` for one category."""
        return {lp.key: lp.value for lp in self.fetch_properties(category)}

    def write_properties(
        self, writes: Mapping[tuple[int, int], tuple[Any, int | None]]
    ) -> None:
        """POST values to ``/api/prop``, mirroring ``StoreProperties``.

        ``writes`` maps ``(propId, subId)`` to ``(value, data_type)`` where
        the value is already typed; it is encoded per
        :func:`encode_property_value`.  Batches of 15, like the app.
        """
        items = list(writes.items())
        for start in range(0, len(items), STORE_BATCH_SIZE):
            body = {
                f"{key[0]:X}_{key[1]:X}": {
                    "id": f"{key[0]:X}_{key[1]:X}",
                    "value": encode_property_value(data_type, value),
                }
                for key, (value, data_type) in items[start : start + STORE_BATCH_SIZE]
            }
            self._authed("POST", "prop", json=body)

    def info(self, timeout: float | None = None) -> ChargerInfo | None:
        """Return the charger's identity from ``GET /api/info``, or None.

        The endpoint answers without a session (My Eve calls it with
        ``skipLogin``, decompiled.js:738901), and returns the whole of the
        identity in one small document -- ``ObjectId``, ``Model``,
        ``Identity``, ``FWVersion`` and ``Type`` -- where the property route
        walks an entire category for the same five fields.  Neither the
        Windows app nor the HA integration uses it.

        None means "ask the properties instead": the endpoint is missing on
        older firmware, and a body that is not the document we expect is not
        worth guessing at.
        """
        try:
            r = self._c.get(self._url("info"), **_timeout_kwargs(timeout))
            r.raise_for_status()
            doc = r.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return None
        if not isinstance(doc, dict):
            return None
        model = str(doc.get("Model") or "") or None
        object_id = str(doc.get("ObjectId") or "")
        raw_version = str(doc.get("FWVersion") or "")
        if not (object_id or model or raw_version):
            return None
        return ChargerInfo(
            object_id=object_id or self.station.object_id,
            identity=str(doc.get("Identity")) if doc.get("Identity") else None,
            model=model,
            family=device_family(str(model or "")),
            firmware=raw_version,
            firmware_version=parse_fw_version(raw_version),
            sockets=_sockets_from_type(doc.get("Type")),
        )

    def basic_info(self) -> ChargerInfo:
        """Return a handful of identifying properties, like the app's Information panel."""
        reply = self.info()
        if reply is not None:
            return reply
        p = self.properties("generic")
        raw_version = str(p.get(P_SW_VERSION, "") or "")
        # Model comes from sysChargePointModel; fall back to the device name
        # (e.g. "NG910").
        model = p.get(P_MODEL) or p.get(P_DEVICE_NAME)
        return ChargerInfo(
            object_id=str(p.get(P_SERIAL) or self.station.object_id),
            identity=p.get(P_IDENTITY),
            model=model,
            family=device_family(str(model or "")),
            firmware=raw_version,
            firmware_version=parse_fw_version(raw_version),
            sockets=p.get(P_NR_SOCKETS),
        )

    # -- firmware -------------------------------------------------------------------------
    def firmware_status(self, timeout: float | None = None) -> tuple[bool, int]:
        """Return ``(uploadInProgress, EFirmwareUpdateStatus)`` from GET /api/firmware.

        ``timeout`` overrides the client's per-request timeout, for polling
        a charger that is mid-reboot (see :data:`REBOOT_POLL_TIMEOUT_S`).
        """
        r = self._authed("GET", "firmware", timeout=timeout)
        text = r.text.replace(",}", "}")  # the app tolerates this trailing-comma quirk
        doc = json.loads(text) if text.strip() else {}
        in_progress = str(doc.get("uploadInProgress", "false")).lower() == "true"
        status_obj = doc.get("OD_fileFirmwareUpdateStatus") or {}
        if isinstance(status_obj, dict):
            status = int(status_obj.get("value", FW_NO_ACTIVE_UPDATE))
        else:
            status = FW_NO_ACTIVE_UPDATE
        return in_progress, status

    def _stream_upload(self, body: bytes, boundary: str) -> int | None:
        """Send one streamed firmware POST; return the HTTP status, or None on a post-body drop.

        The body streams in :data:`UPLOAD_WRITE_SIZE`-byte records with an
        explicit ``Content-Length``. We read only the response status line
        (``stream=True``): the charger normally returns HTTP 200, but should it
        instead drop the connection as it reboots to apply the image, a drop
        after the FULL body was delivered still counts as success (return
        None). A drop before the full body is a real error.
        """
        total = len(body)
        start = time.monotonic()
        last_step = -1

        def on_progress(sent: int) -> None:
            nonlocal last_step
            elapsed = time.monotonic() - start
            if self.on_upload_progress is not None:
                self.on_upload_progress(sent, total, elapsed)
                return
            if not self.debug:
                return  # nobody asked to be told; see on_upload_progress
            # Whoever set no callback gets the debug trace instead: a line
            # every PROGRESS_DEBUG_STEP of the body.
            frac = sent / total
            step = int(frac / PROGRESS_DEBUG_STEP)
            if step > last_step:
                last_step = step
                eta = elapsed * (total - sent) / sent if sent else 0.0
                print(
                    f"[debug] -- upload {frac:.0%} "
                    f"({sent / BYTES_PER_MB:.1f}/{total / BYTES_PER_MB:.1f} MB) "
                    f"elapsed {fmt_duration(elapsed)} eta {fmt_duration(eta)}",
                    file=sys.stderr,
                )

        stream = _FixedChunkStream(body, on_progress=on_progress)
        req = self._c.build_request(
            "POST",
            self._url("firmware"),
            # Override the client's default "Accept: application/json": the
            # firmware endpoint resets the connection ~0.2 s in for a POST that
            # asks for a JSON response. "*/*" is what the app / a raw socket
            # send, and the only Accept the charger will accept here.
            headers={
                "Accept": "*/*",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            timeout=httpx.Timeout(UPLOAD_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
        )
        req.stream = stream
        req.headers["Content-Length"] = str(len(body))
        req.headers.pop("Transfer-Encoding", None)
        try:
            r = self._c.send(req, stream=True)
        except httpx.HTTPError as exc:
            elapsed = time.monotonic() - start
            if stream.sent >= total:
                if self.debug:
                    print(
                        f"[debug] -- upload body fully sent ({stream.sent} B in "
                        f"{elapsed:.1f}s), connection then dropped ({exc}); "
                        f"treating as accepted (charger rebooting to apply).",
                        file=sys.stderr,
                    )
                return None
            raise UploadError(
                f"upload connection dropped after {stream.sent}/{total} B "
                f"in {elapsed:.1f}s: {exc}"
            ) from exc
        try:
            if self.debug:
                print(
                    f"[debug] -- upload sent {stream.sent} B in "
                    f"{time.monotonic() - start:.1f}s; HTTP {r.status_code}",
                    file=sys.stderr,
                )
            return r.status_code
        finally:
            r.close()  # release the (unread) response body / connection

    def upload_firmware(self, data: bytes) -> None:
        """POST the image to /api/firmware as a single, streamed multipart part.

        The image is one part named "firmwarefile"; it streams in small TLS
        records and is accepted only with ``Accept: */*`` -- see the module
        docstring for why each of those matters. Runs on its own fresh
        connection + login (:meth:`_reset_connection`), retrying once on
        401/403 (the session can lapse before the slow upload). ~45-65 s for
        ~1.8 MB.
        """
        boundary = uuid.uuid4().hex
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="firmwarefile"; filename="filename"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + data
            + f"\r\n--{boundary}--\r\n".encode()
        )

        # Fresh connection + fresh login, then the upload is the next request on it.
        self._reset_connection()
        self.login()
        status = self._stream_upload(body, boundary)
        if status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
            self.login()  # session dropped between login and upload; re-auth and retry once
            status = self._stream_upload(body, boundary)
        if status is not None and status != HTTP_OK:
            raise UploadError(f"charger rejected the firmware upload: HTTP {status}")

    def send_command(self, command: str, timeout: float | None = None) -> None:
        """Send one console command to ``POST /api/cmd`` (``SendCommand``).

        The charger's own command console, the same one the app's *Command
        Window* dialog types into. The app itself only ever sends ``reboot``,
        ``txerase``, ``date <timestamp>``, ``eepromx erase config`` and
        ``forcefirmwarepermanent``, but the field is free-form.
        """
        self._authed("POST", "cmd", json={"command": command}, timeout=timeout)

    def commit_firmware(self) -> None:
        """Make the freshly-uploaded firmware permanent (forcefirmwarepermanent)."""
        self.send_command("forcefirmwarepermanent")

    def reboot(self, is_ahp: bool = False) -> None:
        """Ask the charger to restart (``ICULanDevice.SendReboot``).

        NG chargers take the ``reboot`` console command; AHP has a reset
        endpoint, where ``type=hard`` is the equivalent of a power cycle
        (``type=soft`` restarts only the application).
        """
        if is_ahp:
            self._authed("POST", "reset?type=hard", content=b"")
        else:
            self.send_command("reboot")

    def clear_settings(self, is_ahp: bool = False) -> None:
        """Erase the stored configuration (``ICULanDevice.ClearSettings``).

        The charger comes back up on its factory defaults.
        """
        if is_ahp:
            self._authed("POST", "db/reset?dbname=configuration_item", content=b"")
        else:
            self.send_command("eepromx erase config")

    def clear_personal_data(self) -> None:
        """Erase personal data (``ClearPersonalData``): tags, transactions, logs."""
        self._authed("POST", "clearpersonaldata", content=b"")

    def set_password(self, new_password: str) -> None:
        """Set a new unique login password (the app's ``ChangePassword``).

        Used when an upgrade crosses the 5.0 firmware boundary, after which the
        charger requires a unique per-charger password instead of the shared
        default. Mirrors the app: ``POST /api/password`` with the new password,
        while logged in.
        """
        self._authed("POST", "password", json={"password": new_password})

    def set_end_user_pin(self, pin: str) -> None:
        """Set (or, with ``pin=""``, enable without one) the Eve Connect app PIN.

        Mirrors ``ICULanDevice.SetEndUserPin``: the same ``POST
        /api/password`` endpoint as the admin login password, but with
        ``username: "end user"`` -- a second, independent credential the
        app's *Eve Connect app access* dialog manages (``DlgEndUserPin``).
        An empty pin enables access without requiring one.
        """
        self._authed("POST", "password", json={"username": "end user", "password": pin})

    def disable_end_user_access(self) -> None:
        """Disable the Eve Connect app PIN entirely (``DisableEndUserAccess``)."""
        self._authed("POST", "password", json={"username": "end user", "reset": True})

    def reset_password(self, code: str) -> None:
        """Reset the login password to the default with a recovery code.

        ``POST /api/prc`` with the code printed on the charger (the app's
        ``ResetPassword``).  Runs *without* a session -- it is the way back
        in when the password is lost.  The charger answers 403 for a wrong
        code, 429 with ``lockout_remaining_seconds`` after too many tries,
        and 503 where recovery is not available.
        """
        self._c.post(self._url("prc"), json={"code": code}).raise_for_status()

    def set_temporary_password(self, new_password: str, hours: int) -> None:
        """Set a password that expires after ``hours`` (``CreateTempPassword``).

        ``POST /api/temporarypassword``; the charger reverts to the previous
        password on its own when the time is up.  Requires a session.
        """
        self._authed(
            "POST",
            "temporarypassword",
            json={"password": new_password, "expiration": hours},
        )

    def set_datetime(
        self, is_ahp: bool = False, when: datetime | None = None
    ) -> datetime:
        """Set the charger's clock to ``when`` (default: now), in UTC.

        Mirrors ``ICULanDevice.SetDate``, which does two things: it writes
        ``sysDateTime`` (:data:`P_DATE_TIME`, milliseconds since the Unix
        epoch) and then tells the firmware separately -- NG chargers take the
        ``date`` console command, AHP a ``POST /api/datetime`` -- both
        formatted as ``yyyy-MM-dd HH:mm:ss`` in UTC (``SendDatetime``).

        The app calls this before every upload, and so do we: firmware
        signature validation checks certificate validity against the device
        clock, so an unset/wrong clock makes the charger reject a valid image
        regardless of which version you send.

        Sending "now" means the moment each request leaves, not the moment
        this method was entered: the command below is what actually moves the
        clock, and it goes out one whole property-write round trip later.
        Stamping both from a single reading left the charger a couple of
        seconds behind for as long as it ran afterwards -- exactly the round
        trip.  The command's whole-second field is rounded rather than
        truncated for the same reason, and aimed :data:`MAX_CLOCK_LEAD_S`-capped
        half a round trip ahead so it is right when it lands.  An explicit
        ``when`` is used as given: a caller naming an instant means that one.

        Returns the moment the clock was set to.
        """
        pinned = None if when is None else when.astimezone(timezone.utc)
        first = pinned or datetime.now(timezone.utc)
        started = time.monotonic()
        round_trip = 0.0
        try:
            self.write_properties(
                {P_DATE_TIME: (int(first.timestamp() * 1000), UNSIGNED64)}
            )
            round_trip = time.monotonic() - started
        except httpx.HTTPStatusError:
            # Firmware that does not expose the property still takes the
            # command below, which is what actually moves the clock.
            pass
        if pinned is not None:
            moment = pinned
        else:
            lead = min(round_trip / 2, MAX_CLOCK_LEAD_S)
            moment = datetime.now(timezone.utc) + timedelta(seconds=lead + 0.5)
        # The stamp carries whole seconds; keep the returned moment to the
        # same resolution so it says what the charger was actually told.
        moment = moment.replace(microsecond=0)
        stamp = moment.strftime("%Y-%m-%d %H:%M:%S")
        if is_ahp:
            self._authed(
                "POST",
                "datetime",
                content=f'"{stamp}"'.encode(),
                headers={"Content-Type": "application/json"},
            )
        else:
            self._authed("POST", "cmd", json={"command": f"date {stamp}"})
        return moment

    def set_domain_item(self, item_type: int, data: bytes) -> None:
        """Install one write-only key or certificate (``ICUDomain.AddOrUpdateItem``).

        ``POST /api/domain`` with ``{"cmd":"add","type":<n>,"data":"<hex>"}``,
        where the hex is the value's bytes, uppercase and unseparated.  This
        is the only way in: the properties behind these items are ``wo`` in
        the EDS and ``POST /api/prop`` will not write them.  See
        :mod:`alfenctl.secret` for the item types.
        """
        body = {"cmd": "add", "type": int(item_type), "data": data.hex().upper()}
        self._authed("POST", "domain", json=body)
