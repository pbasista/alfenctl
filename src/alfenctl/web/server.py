"""The local web server: routing, guards, the event stream and the static app.

Deliberately the standard library and nothing else.  Everything behind it is
synchronous -- one httpx client on one worker thread -- so a thread-per-
connection server is the shape that fits: an event stream is a handler
thread blocking on a queue, and there is no async bridge to build.

What the transport layer has to get right, since there is no framework
doing it for us:

* **Streaming.** SSE responses carry no ``Content-Length``, so they close
  the connection when they end and say so up front.
* **Who may connect.** Off loopback the server requires a token, which
  arrives once in the URL and is then kept in a ``SameSite=Strict`` cookie.
* **DNS rebinding.** A page on the open internet can point a name it
  controls at ``127.0.0.1`` and drive a local server from the victim's
  browser.  Names are therefore refused outright: the ``Host`` header must
  be an IP literal, ``localhost``, or a name the user allowed explicitly.
* **Cross-site POSTs.** Cookie auth alone would let another origin submit a
  form here, so every write also needs the ``X-Alfen-UI`` header, which a
  cross-origin form cannot set without a preflight we never answer.
"""

from __future__ import annotations

import errno
import ipaddress
import json
import os
import secrets
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from alfenctl.errors import AlfenError
from alfenctl.web import schema
from alfenctl.web.api import (
    ROUTES,
    ApiError,
    Context,
    Request,
    Response,
    make_poll,
    parse_query,
)
from alfenctl.web.events import HEARTBEAT_INTERVAL_S, Broadcaster
from alfenctl.web.session import StationWorker, Target, WorkerBusyError

DEFAULT_PORT = 8088
DEFAULT_HOST = "127.0.0.1"

# The cookie the browser keeps the access token in.
TOKEN_COOKIE = "alfenctl_token"
# The header a same-origin fetch sets and a cross-origin form cannot.
UI_HEADER = "X-Alfen-UI"

# Concurrent event streams we will hold open.  Each costs a thread; a
# handful of browsers with a tab each stays far below this, and the cap
# keeps a client that reconnects in a loop from exhausting the process.
MAX_STREAMS = 24

# How long a browser waits before reconnecting a stream that dropped.  Kept
# short deliberately: a tab left open from an earlier run is how a restart
# finds out there is already a window to raise instead of opening another.
STREAM_RETRY_MS = 1000

# How long a starting server waits for such a tab to come back before it
# gives up and opens a new one.
BROWSER_GRACE_S = 2.0

# Largest request body we will read at all (uploads are capped lower still
# by the API layer; this is the guard against a body that never ends).
MAX_BODY_BYTES = 64 * 1024 * 1024

# How often the accept loop looks up to see whether it has been shut down;
# this is the floor on how long Ctrl+C takes to reach the prompt.
SHUTDOWN_POLL_S = 0.05

# Exit status for a run that was interrupted, by the shell's convention of
# 128 plus the signal number (SIGINT is 2).
EXIT_INTERRUPTED = 130

STATIC_DIR = Path(__file__).with_name("static")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json",
}

HTTP_OK = 200
HTTP_NO_CONTENT = 204
HTTP_NOT_MODIFIED = 304


class UIServer(ThreadingHTTPServer):
    """The HTTP server, plus everything the handlers need to reach."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        context: Context,
        events: Broadcaster,
        token: str,
        allowed_hosts: frozenset[str],
    ) -> None:
        """Bind the server and record its shared state."""
        self.context = context
        self.events = events
        self.token = token
        self.allowed_hosts = allowed_hosts
        self.stopping = threading.Event()
        self.streams = 0
        self._stream_lock = threading.Lock()
        super().__init__(address, UIHandler)

    def claim_stream(self) -> bool:
        """Take one of the event-stream slots, if any is left."""
        with self._stream_lock:
            if self.streams >= MAX_STREAMS:
                return False
            self.streams += 1
            return True

    def release_stream(self) -> None:
        """Give an event-stream slot back."""
        with self._stream_lock:
            self.streams = max(0, self.streams - 1)

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Swallow the noise a browser makes when it walks away mid-request.

        A closed tab, a cancelled fetch or a reload all show up here as a
        broken pipe or a reset; the default handler prints a full traceback
        per occurrence, which would bury the one line the user wants.

        This belongs on the server, not on the handler: socketserver calls
        it on whatever accepted the connection.
        """
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        if self.context.debug:
            super().handle_error(request, client_address)


class UIHandler(BaseHTTPRequestHandler):
    """One request (or one long-lived event stream)."""

    protocol_version = "HTTP/1.1"
    server_version = "alfenctl"
    sys_version = ""

    @property
    def ui(self) -> UIServer:
        """The server, typed: socketserver types this as the base class."""
        return cast(UIServer, self.server)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Keep request logging off the terminal unless --debug asked for it.

        The parameter keeps the base class's name, builtin or not, so a
        caller passing it by keyword still reaches this override.
        """
        if self.ui.context.debug:
            sys.stderr.write(f"[debug] -- ui {self.address_string()} {format % args}\n")

    # --- guards ------------------------------------------------------------------

    def _host_allowed(self) -> bool:
        """Refuse a Host header that is a name we were not told to expect."""
        host = urlsplit(f"//{self.headers.get('Host', '')}").hostname or ""
        host = host.strip("[]").lower()
        if not host:
            return False
        if host in self.ui.allowed_hosts:
            return True
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return False
        return True  # an IP literal cannot be re-pointed by DNS

    def _token_ok(self) -> tuple[bool, str | None]:
        """Check the access token; returns (allowed, token to set as a cookie)."""
        if not self.ui.token:
            return True, None
        supplied = parse_query(urlsplit(self.path).query).get("token")
        if supplied and secrets.compare_digest(supplied, self.ui.token):
            return True, supplied
        cookies = self.headers.get("Cookie", "")
        for part in cookies.split(";"):
            name, _, value = part.strip().partition("=")
            if name == TOKEN_COOKIE and secrets.compare_digest(value, self.ui.token):
                return True, None
        if secrets.compare_digest(self.headers.get("X-Alfen-Token", ""), self.ui.token):
            return True, None
        return False, None

    # --- dispatch ----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        """Serve the app, the event stream, or a read endpoint."""
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        """Serve a write endpoint."""
        self._dispatch("POST")

    def do_HEAD(self) -> None:  # noqa: N802
        """Answer a HEAD like a GET without the body."""
        self._dispatch("GET", head_only=True)

    def _dispatch(self, method: str, *, head_only: bool = False) -> None:
        split = urlsplit(self.path)
        path = split.path.rstrip("/") or "/"
        if not self._host_allowed():
            self._send_error_page(
                403,
                "This server only answers to an IP address or 'localhost'. "
                "Start it with --allow-host NAME to use a hostname.",
            )
            return
        allowed, set_cookie = self._token_ok()
        if not allowed:
            self._send_error_page(
                403, "Missing or wrong access token. Open the link the server printed."
            )
            return
        if set_cookie is not None and not path.startswith("/api/"):
            # The token arrived in the URL: stash it and reload without it,
            # so it stops appearing in the address bar and in referrers.
            self._redirect(split.path or "/", set_cookie)
            return
        try:
            if path == "/api/events":
                self._serve_events()
                return
            if path.startswith("/api/"):
                self._serve_api(method, path, split.query)
                return
            if method != "GET":
                self._send_error_page(405, "method not allowed")
                return
            self._serve_static(path, head_only=head_only)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser went away mid-reply; nothing to report

    # --- API ---------------------------------------------------------------------

    def _serve_api(self, method: str, path: str, query: str) -> None:
        route = ROUTES.get((method, path))
        if route is None:
            self._send_json(404, {"error": f"no such endpoint: {method} {path}"})
            return
        if method == "POST" and not self.headers.get(UI_HEADER):
            self._send_json(403, {"error": f"missing {UI_HEADER} header"})
            return
        if route.write and self.ui.context.read_only:
            self._send_json(
                403,
                {
                    "error": "this server is running read-only; "
                    "nothing on the charger can be changed from here"
                },
            )
            return
        body = self._read_body()
        if body is None:
            return
        request = Request(method=method, path=path, query=parse_query(query), body=body)
        try:
            response = route.handler(self.ui.context, request)
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except WorkerBusyError as exc:
            self._send_json(409, {"error": str(exc)})
        except AlfenError as exc:
            # A charger or an input said no.  That is the client's problem to
            # fix, not a server fault, so it does not deserve a 500.
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - every failure becomes a reply
            self._report_failure(exc)
        else:
            self._send_response(response)

    def _report_failure(self, exc: BaseException) -> None:
        """Turn an unexpected failure into a 500 (and a traceback in debug)."""
        from alfenctl.web.session import format_traceback

        if self.ui.context.debug:
            sys.stderr.write(f"[debug] -- ui {format_traceback(exc)}\n")
        message = str(exc).strip() or exc.__class__.__name__
        self._send_json(500, {"error": message, "kind": exc.__class__.__name__})

    def _read_body(self) -> bytes | None:
        """Read the request body, or answer an error and return None."""
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._send_json(400, {"error": "bad Content-Length"})
            return None
        if length < 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "request body too large"})
            return None
        return self.rfile.read(length) if length else b""

    # --- event stream ------------------------------------------------------------

    def _serve_events(self) -> None:
        """Hold one Server-Sent Events connection open until it goes away."""
        if not self.ui.claim_stream():
            self._send_json(503, {"error": "too many open event streams"})
            return
        self.close_connection = True  # no Content-Length: the body ends at close
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            # Reconnect quickly: this is what lets a tab from an earlier run
            # be found and raised, rather than a second one being opened.
            self._write_chunk(f"retry: {STREAM_RETRY_MS}\n\n".encode())
            with self.ui.events.subscribe(self._describe_client()) as subscription:
                # The stream's first event tells this browser which of the
                # watchers on /api/clients is itself; nothing else can, since
                # several tabs share one address and one user agent.
                payload = json.dumps({"clientId": subscription.client.get("id")})
                self._write_chunk(f"event: hello\ndata: {payload}\n\n".encode())
                while not self.ui.stopping.is_set():
                    event = subscription.get(HEARTBEAT_INTERVAL_S)
                    if subscription.closed:
                        break
                    if event is None:
                        self._write_chunk(b": ping\n\n")  # prove the socket is alive
                        continue
                    payload = json.dumps(event.data, default=str)
                    self._write_chunk(
                        f"event: {event.name}\nid: {event.seq}\ndata: {payload}\n\n".encode()
                    )
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the tab was closed
        finally:
            self.ui.release_stream()

    def _describe_client(self) -> dict[str, Any]:
        """Who is opening this stream, as far as the request can say."""
        peer = self.client_address if isinstance(self.client_address, tuple) else ()
        return {
            "address": peer[0] if peer else "",
            "port": peer[1] if len(peer) > 1 else None,
            "agent": self.headers.get("User-Agent", "") or "",
            "since": time.time(),
        }

    def _write_chunk(self, data: bytes) -> None:
        """Write one piece of the stream and push it out immediately."""
        self.wfile.write(data)
        self.wfile.flush()

    # --- static files ------------------------------------------------------------

    def _serve_static(self, path: str, *, head_only: bool = False) -> None:
        """Serve the built app, falling back to index.html for app routes."""
        relative = path.lstrip("/") or "index.html"
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._send_error_page(403, "forbidden")
            return
        if not target.is_file():
            target = STATIC_DIR / "index.html"
        if not target.is_file():
            self._send_error_page(
                500,
                "The web UI files are missing from this installation "
                f"(expected them in {STATIC_DIR}).",
            )
            return
        body = target.read_bytes()
        self._send_response(
            Response(
                status=200,
                body=b"" if head_only else body,
                content_type=CONTENT_TYPES.get(
                    target.suffix, "application/octet-stream"
                ),
                headers={"Cache-Control": "no-cache", "Content-Length": str(len(body))},
            )
        )

    # --- replies -----------------------------------------------------------------

    def _redirect(self, location: str, token: str) -> None:
        """Send the token to a cookie and reload the page without it."""
        self.send_response(303)
        self.send_header("Location", location or "/")
        self.send_header(
            "Set-Cookie",
            f"{TOKEN_COOKIE}={token}; Path=/; SameSite=Strict; Max-Age=604800",
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        """Send one JSON reply."""
        self._send_response(
            Response(status=status, body=json.dumps(payload).encode("utf-8"))
        )

    def _send_error_page(self, status: int, message: str) -> None:
        """Send a refusal a person can read in a browser tab."""
        self._send_response(
            Response(
                status=status,
                body=f"alfenctl ui: {message}\n".encode(),
                content_type="text/plain; charset=utf-8",
            )
        )

    def _send_response(self, response: Response) -> None:
        """Write a complete reply."""
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        if "Content-Length" not in response.headers:
            self.send_header("Content-Length", str(len(response.body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if response.body and self.command != "HEAD":
            self.wfile.write(response.body)


def local_addresses() -> list[str]:
    """Best guess at the addresses others could reach this machine on."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.2)
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1: routed nowhere
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    return found


def raise_open_tab(
    host: str, port: int, *, timeout: float = 1.0
) -> dict[str, Any] | None:
    """Ask an alfenctl already serving this port to raise its browser tab.

    Returns the reply -- which names the app and the browsers it reached --
    or ``None`` if nobody answered as alfenctl.  The reply has to name the
    app: something else entirely may be listening on that port, and a
    stranger's 200 is not a reason to say the UI is already open.
    """
    import http.client

    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request(
                "POST",
                "/api/focus",
                body=b"{}",
                headers={"Content-Type": "application/json", UI_HEADER: "1"},
            )
            response = conn.getresponse()
            doc = json.loads(response.read() or b"{}")
        finally:
            conn.close()
    except (OSError, ValueError, http.client.HTTPException):
        return None
    if response.status == HTTP_OK and doc.get("app") == "alfenctl":
        return doc
    return None


def show_the_page(
    url: str, events: Broadcaster, *, grace: float = BROWSER_GRACE_S
) -> bool:
    """Raise the tab that already has this page open, or open a new one.

    No browser can be told from the outside to switch to a tab it already
    has, so the page is told to raise itself instead: a tab left over from an
    earlier run reconnects to the stream within :data:`STREAM_RETRY_MS`, and
    a ``focus`` event reaches it there.  Only if nothing has reconnected by
    the end of the grace period is a new tab opened.  Returns whether an
    existing tab was found.
    """
    import webbrowser

    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if events.subscriber_count:
            events.publish("focus", {"at": time.time()})
            print(
                "  a browser already has this page open -- raising that tab", flush=True
            )
            for name in schema.name_watchers(events.clients()):
                print(f"    {name}", flush=True)
            return True
        time.sleep(0.05)
    webbrowser.open(url)
    return False


def _begin_teardown(server: UIServer, worker: StationWorker) -> None:
    """Start everything that has to end, without waiting for any of it.

    Runs off the signal handler rather than in it: each of these takes a
    lock some other thread may be holding, and a handler runs on the main
    thread, where blocking on one is how a process hangs on Ctrl+C instead
    of stopping on it.
    """
    worker.stop(timeout=0)  # tell it to stand down; do not wait here
    server.events.shutdown()  # end the event streams, waking their threads
    server.shutdown()  # stop accepting, and wait for the loop to notice


def _install_stop_handlers(
    server: UIServer, worker: StationWorker
) -> Callable[[], None]:
    """Make Ctrl+C (and SIGTERM) stop the server; returns a restore callback.

    ``serve_forever`` waits in ``selectors.select``, and an interrupt there is
    not guaranteed to surface as ``KeyboardInterrupt`` -- on this platform it
    does not, and the server keeps the port.  So the signal is handled
    explicitly instead.  ``shutdown`` blocks until the loop has stopped and
    would deadlock if called from the loop's own thread, which is exactly where
    a signal handler runs, hence the throwaway thread.

    Everything that can be started here is started here rather than in
    ``serve``'s ``finally``, because they are independent and the slow one
    should not be waiting on its turn: the event streams end, the accept
    loop stops and the station worker is told to stand down all at once.
    A second Ctrl+C is taken to mean the first one was not fast enough and
    leaves immediately, which is the usual contract for one.
    """
    stopping = threading.Event()

    def handler(signum: int, frame: Any) -> None:
        if stopping.is_set():
            # Asked twice: stop asking politely.  Nothing here writes to
            # disk, so there is nothing a second pass could corrupt.
            os._exit(EXIT_INTERRUPTED)
        stopping.set()
        print("\nStopping...", flush=True)
        server.stopping.set()
        threading.Thread(target=_begin_teardown, args=(server, worker)).start()

    previous: list[tuple[int, Any]] = []
    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            previous.append((signum, signal.signal(signum, handler)))
        except ValueError:
            # Not the main thread -- the embedding process owns the signals.
            pass

    def restore() -> None:
        for signum, old in previous:
            try:
                signal.signal(signum, old)
            except (ValueError, TypeError):
                pass

    return restore


def serve(
    *,
    target: Target | None,
    config: Any,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str | None = None,
    read_only: bool = False,
    open_browser: bool = True,
    poll_interval: float | None = None,
    idle_timeout: float | None = None,
    allow_hosts: tuple[str, ...] = (),
    discover_time: float = 2.0,
    debug: bool = False,
) -> int:
    """Run the web UI until interrupted; returns a process exit code."""
    from alfenctl.web.session import (
        DEFAULT_IDLE_TIMEOUT_S,
        DEFAULT_POLL_INTERVAL_S,
    )

    loopback = host in ("127.0.0.1", "::1", "localhost")
    if token is None:
        token = "" if loopback else secrets.token_urlsafe(16)

    events = Broadcaster()
    worker = StationWorker(
        target,
        events,
        poll_interval=poll_interval or DEFAULT_POLL_INTERVAL_S,
        idle_timeout=idle_timeout or DEFAULT_IDLE_TIMEOUT_S,
    )
    context = Context(
        worker=worker,
        read_only=read_only,
        debug=debug,
        discover_time=discover_time,
        config=config,
    )
    worker.set_poll_fn(make_poll(context))
    worker.start()

    allowed = frozenset(
        {"localhost", *(h.strip().lower() for h in allow_hosts if h.strip())}
    )
    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    try:
        server = UIServer(
            (host, port),
            context=context,
            events=events,
            token=token,
            allowed_hosts=allowed,
        )
    except OSError as exc:
        worker.stop()
        # The usual reason the port is taken is that this is the second
        # `alfenctl ui` -- so before failing, ask the first one to bring its
        # browser tab forward, which is what the user wanted anyway.
        taken = getattr(exc, "errno", None) == errno.EADDRINUSE
        reply = raise_open_tab(shown_host, port) if taken and open_browser else None
        if reply is not None:
            print(f"alfenctl ui is already serving on http://{shown_host}:{port}/")
            print("  raised the browser tab it had already opened")
            # Named by the other process, which is the only one that can see
            # who is on its stream.
            for name in reply.get("watching") or []:
                print(f"    {name}")
            return 0
        print(f"Cannot listen on {host}:{port}: {exc}", file=sys.stderr)
        return 1

    suffix = f"?token={token}" if token else ""
    url = f"http://{shown_host}:{server.server_port}/{suffix}"
    print(f"alfenctl ui is serving on {url}", flush=True)
    if read_only:
        print("  read-only: nothing on the charger can be changed from the browser")
    if not loopback:
        for address in local_addresses():
            print(f"  shareable: http://{address}:{server.server_port}/{suffix}")
        if token:
            print("  the link includes an access token -- share it deliberately")
    print("  press Ctrl+C to stop", flush=True)

    if open_browser:
        threading.Thread(target=show_the_page, args=(url, events), daemon=True).start()

    stop = _install_stop_handlers(server, worker)
    try:
        server.serve_forever(poll_interval=SHUTDOWN_POLL_S)
    except KeyboardInterrupt:
        print("\nStopping...", flush=True)
    finally:
        stop()
        server.stopping.set()
        events.shutdown()
        server.shutdown()
        server.server_close()
        worker.stop()
    return 0


__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "UIServer", "raise_open_tab", "serve"]
