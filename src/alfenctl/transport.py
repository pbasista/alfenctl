"""The wire: one HTTP connection to one charger, and what it takes to hold it.

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
* The session lapses after a short idle, so :meth:`ChargerTransport.request`
  re-logs-in and retries once on 401/403, like the app's
  ``HandleUnsuccessfulRequest``.

The firmware upload (:meth:`ChargerTransport.stream_upload`) has four
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

What a *request means* is not here.  :mod:`alfenctl.charger` sits on top of
this with the fifty-odd endpoints the charger offers, so that reading this
file is reading one subject: how the connection is made, kept, re-made when
the charger drops it, and how a 2 MB image is pushed through it without the
firmware resetting the socket.

This is the one module under ``src/alfenctl/`` that writes to stderr, and only
under ``--debug``, whose documented job is exactly that: log every HTTP
request and response. Nothing else here prints.
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from devicectl.progress import BYTES_PER_MB, PROGRESS_DEBUG_STEP, fmt_duration

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
    VISIBLE_STRING,
)
from alfenctl.errors import AlfenError

# --- HTTP status codes we branch on -----------------------------------------------------

HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404

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

# A property id splits into exactly two parts: the object id and the sub-index.
PROP_ID_PARTS = 2


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


class ChargerTransport:
    """One authenticated HTTP connection to one charger.

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
        # reports (devicectl.report.Reporter.sending is what gets hooked up).
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

    def __enter__(self) -> "ChargerTransport":
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

    def request(
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

    def send_command(self, command: str, timeout: float | None = None) -> None:
        """Send one console command to ``POST /api/cmd`` (``SendCommand``).

        Windows sends the common maintenance commands; MyEve also supplies
        flash, display, modem, test and database commands. The field remains
        free-form. An accepted POST does not prove handler execution or
        authorization; advanced commands may require an SSA session.
        """
        self.request("POST", "cmd", json={"command": command}, timeout=timeout)

    def stream_upload(self, body: bytes, boundary: str) -> int | None:
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
