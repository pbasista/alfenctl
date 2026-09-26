"""The endpoints the browser calls, and what they run against the charger.

Handlers never touch the charger directly: each one hands a function to the
:class:`~alfenctl.web.session.StationWorker`, which owns the single
connection.  A handler is therefore short -- work out what to run, submit it,
shape the reply -- and the interesting code stays in the modules the CLI
already uses (:mod:`alfenctl.status`, :mod:`alfenctl.clock`,
:mod:`alfenctl.logo`, and so on).

Two kinds of endpoint:

* the ordinary ones submit with :meth:`StationWorker.run` and block their
  request thread until the answer comes back;
* firmware and logo uploads submit with :meth:`StationWorker.start_job` and
  answer immediately with a job id, because they hold the charger for a
  minute or more and their progress belongs on the event stream.

Routes marked ``write`` are refused outright when the server was started
with ``--read-only``, so a dashboard can be shared without handing over the
ability to change anything.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx
from devicectl import fields
from devicectl.report import Reporter
from devicectl.web.http import ApiError, Request, Response, Route, discard, ok, spool

from alfenctl import (
    __version__,
    access,
    clock,
    console,
    controls,
    hardware,
    loadbalancing,
    logs,
    properties,
    scn,
    setup,
    status as status_mod,
)
from alfenctl.charger import AlfenCharger
from alfenctl.errors import AlfenError
from alfenctl.transport import HTTP_NOT_FOUND
from alfenctl.upgrade import install, send_image
from alfenctl.web import schema
from alfenctl.web.progress import (
    DOWNLOAD_SHARE_OF_JOB,
    download_reporter,
    upgrade_reporter,
)
from alfenctl.web.session import Job, StationWorker, Target

# The largest upload we will take from the browser.  A firmware image is
# ~2 MB and a logo package well under 1 MB; anything at this size is a
# mistake, and we would rather say so than buffer it.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024

# How many log lines the log view asks for.
LOG_PAGE_LINES = 200

# What firmware without /api/chargingprofiles answers with.

# The diagnostic protocol identifies requests with a byte-sized sequence ID.
DIAGNOSTIC_SEQUENCE_MAX = 255


class Live:
    """The part of the context that changes while the server is running.

    One :class:`Context` is built at start-up and shared by every request
    thread and by the worker thread, so anything on it that *changes* is
    shared mutable state.  There are only three such values and they are all
    small, but two of them are written from both sides -- the log cursor
    moves on a request thread when the log view pages and on the worker
    thread on every follow beat -- so they are kept here, behind one lock,
    rather than as bare attributes that merely look settled.

    Nothing here is a consistency boundary: each value stands alone, and the
    lock exists so that a reader always sees one whole value rather than to
    make a group of them agree.
    """

    def __init__(self) -> None:
        """Start with nothing read and nothing being followed."""
        self._lock = threading.Lock()
        self._sockets = 1
        self._follow_logs = False
        self._log_last_id: int | None = None

    @property
    def sockets(self) -> int:
        """How many sockets the last read reported."""
        with self._lock:
            return self._sockets

    @sockets.setter
    def sockets(self, count: int) -> None:
        with self._lock:
            self._sockets = count

    @property
    def follow_logs(self) -> bool:
        """Whether the live refresh should also page the event log."""
        with self._lock:
            return self._follow_logs

    @follow_logs.setter
    def follow_logs(self, follow: bool) -> None:
        with self._lock:
            self._follow_logs = follow

    @property
    def log_last_id(self) -> int | None:
        """The newest log line already sent to the browsers."""
        with self._lock:
            return self._log_last_id

    @log_last_id.setter
    def log_last_id(self, last: int | None) -> None:
        with self._lock:
            self._log_last_id = last

    def forget(self) -> None:
        """Drop everything read from the station we were just talking to."""
        with self._lock:
            self._sockets = 1
            self._log_last_id = None


class CloudLogins:
    """Half-finished manufacturer sign-ins, from the authorize URL to the code.

    The web UI runs the very flow the CLI's ``cloud login`` does: the server
    makes the PKCE pair and a state, hands back the URL to open, and holds the
    verifier until the browser comes back with the code.  The password is
    never seen here -- it is typed on Alfen's own hosted page -- and a pending
    sign-in is keyed by its state and forgotten after a short while, so an
    abandoned one does not linger.
    """

    _TTL_S = 600.0

    def __init__(self) -> None:
        """Start with no sign-in in flight."""
        self._lock = threading.Lock()
        # state -> (verifier, redirect_uri, born)
        self._pending: dict[str, tuple[str, str, float]] = {}

    def begin(self, origin: str | None = None) -> tuple[str, bool]:
        """Start a sign-in; return ``(url, loopback)`` for the page to open.

        When the page's ``origin`` is a ``http://localhost:<port>`` Alfen's
        client accepts, the redirect comes back to that same origin and the
        code is read without a paste (``loopback`` True).  Otherwise the mobile
        scheme is used and the page falls back to pasting (``loopback`` False).
        """
        from alfenctl import cloud

        verifier, challenge = cloud.make_pkce()
        state = secrets.token_urlsafe(16)
        redirect_uri, loopback = cloud.loopback_redirect(origin)
        with self._lock:
            self._prune()
            self._pending[state] = (verifier, redirect_uri, time.time())
        url = cloud.authorize_url(challenge, state, redirect_uri=redirect_uri)
        return url, loopback

    def complete(self, client: httpx.Client, redirected: str) -> Any:
        """Trade the redirect for a token, matching it to its sign-in.

        Works for both flows: a loopback lands the browser on the UI's own URL
        (from which the page hands the whole address here), and the paste flow
        hands the address the browser was left on.
        """
        from alfenctl import cloud

        text = redirected.strip()
        query = urllib.parse.urlparse(text).query if "?" in text else text
        state = urllib.parse.parse_qs(query).get("state", [None])[0]
        with self._lock:
            self._prune()
            entry = self._pending.pop(state, None) if state else None
        if entry is None:
            raise cloud.CloudError(
                "this sign-in was not started here, or has expired; start it again"
            )
        verifier, redirect_uri, _born = entry
        code = cloud.code_from_redirect(text, expected_state=state)
        return cloud.exchange_code(client, code, verifier, redirect_uri=redirect_uri)

    def _prune(self) -> None:
        """Drop sign-ins past their life (called with the lock held)."""
        cutoff = time.time() - self._TTL_S
        stale = [s for s, (_v, _r, born) in self._pending.items() if born < cutoff]
        for state in stale:
            del self._pending[state]


@dataclass(frozen=True)
class Context:
    """Everything a handler needs besides the request.

    Frozen on purpose: one of these is built when the server starts and is
    then read by every request thread at once.  What changes while it runs
    is :attr:`live`, and only that.
    """

    worker: StationWorker
    read_only: bool = False
    debug: bool = False
    discover_time: float = 2.0
    config: Any = None
    live: Live = field(default_factory=Live)
    cloud_logins: CloudLogins = field(default_factory=CloudLogins)

    @property
    def catalog(self) -> Any:
        """The EDS catalog, parsed once per process and shared."""
        from alfenctl.eds import load_catalog

        return load_catalog()


# --- reads -------------------------------------------------------------------------------


def get_state(ctx: Context, req: Request) -> Response:
    """Everything a freshly loaded page needs before it subscribes."""
    return ok(
        {
            "version": __version__,
            "readOnly": ctx.read_only,
            "link": ctx.worker.link_state(),
            "info": schema.info_json(ctx.worker.info),
            "jobs": ctx.worker.jobs(),
            "followLogs": ctx.live.follow_logs,
            "hasTarget": ctx.worker.target is not None,
            "cloudSignedIn": _cloud_token_available(),
        }
    )


def _cloud_token_available() -> bool:
    """Whether a cached (or env) Alfen token exists, so a lookup needs no paste.

    Only presence is checked, not that the token is still live -- a stale one
    is renewed from its refresh half when the lookup runs.  This is what lets
    the License card show "signed in" straight after a page reload, and after
    a sign-in the CLI's ``cloud login`` did.
    """
    from alfenctl import cloud
    from alfenctl.config import default_config_dir

    try:
        return cloud.token_from_sources(config_dir=default_config_dir()) is not None
    except cloud.CloudError:
        return False


def get_stations(ctx: Context, req: Request) -> Response:
    """Stations from the config file, plus whatever mDNS finds right now.

    Discovery does not touch the charger's API, so it runs on the request
    thread instead of queueing behind whatever the worker is doing.
    """
    configured = []
    if ctx.config is not None:
        for name in sorted(getattr(ctx.config, "stations", {}) or {}):
            entry = ctx.config.station(name)
            configured.append(
                {
                    "name": name,
                    "host": getattr(entry, "host", "") or "",
                    "source": "config",
                }
            )
    found = []
    if req.flag("discover", True):
        from alfenctl.discovery import discover

        for station in discover(ctx.discover_time):
            found.append(
                {
                    "name": station.object_id or station.ip,
                    "host": station.ip,
                    "port": station.port,
                    "https": station.https,
                    "source": "mdns",
                }
            )
    return ok({"configured": configured, "discovered": found})


def _read_status(ctx: Context, charger: AlfenCharger) -> dict[str, Any]:
    """Read one live snapshot and render it for the page.

    The reading itself is :func:`alfenctl.status.collect`, which is what the
    CLI calls too -- categories plus the ids the walk does not carry -- so a
    number in the browser is the number ``alfenctl status`` prints.
    """
    snapshot = schema.status_json(status_mod.collect(charger, ctx.live.sockets or 1))
    snapshot["at"] = time.time()
    return snapshot


def get_dashboard(ctx: Context, req: Request) -> Response:
    """One connection's worth of everything the dashboard shows."""

    def read(charger: AlfenCharger) -> dict[str, Any]:
        info = charger.basic_info()
        ctx.live.sockets = info.sockets or 1
        doc: dict[str, Any] = {
            "info": schema.info_json(info),
            "status": _read_status(ctx, charger),
        }
        # Each of these is a separate ids= query, and a charger that does not
        # answer for one should still give us the rest of the page.
        for name, reader in (
            ("hardware", lambda: schema.hardware_json(hardware.read(charger))),
            ("clock", lambda: schema.clock_json(clock.read(charger))),
            ("setup", lambda: schema.setup_json(setup.read(charger))),
            ("controls", lambda: schema.controls_json(controls.read(charger))),
            ("display", _display_reader(charger, info)),
            ("license", _license_reader(charger, info)),
            (
                "loadbalancing",
                lambda: schema.loadbalancing_json(loadbalancing.read(charger)),
            ),
        ):
            try:
                doc[name] = reader()
            except (httpx.HTTPError, AlfenError, ValueError, RuntimeError) as exc:
                doc[name] = None
                doc.setdefault("warnings", []).append(f"{name}: {exc}")
        return doc

    doc = ctx.worker.run("Reading charger information", read)
    ctx.worker.events.publish("status", doc["status"], sticky=True)
    ctx.worker.events.publish("info", doc["info"] or {}, sticky=True)
    return ok(doc)


def _display_reader(charger: AlfenCharger, info: Any) -> Callable[[], Any]:
    """Bind the display read to one charger, with the model already in hand."""

    def read() -> Any:
        from alfenctl.logo import read_display

        return schema.display_json(read_display(charger, getattr(info, "model", None)))

    return read


def _license_reader(charger: AlfenCharger, info: Any) -> Callable[[], Any]:
    """Bind the license read to one charger and its identity."""

    def read() -> Any:
        from alfenctl.license import read_license

        return schema.license_json(read_license(charger), info)

    return read


def get_status(ctx: Context, req: Request) -> Response:
    """One live status reading."""
    snapshot = ctx.worker.run(
        "Reading status", lambda charger: _read_status(ctx, charger)
    )
    ctx.worker.events.publish("status", snapshot, sticky=True)
    return ok(snapshot)


def get_categories(ctx: Context, req: Request) -> Response:
    """List the property categories this charger publishes."""
    names = ctx.worker.run("Reading categories", lambda charger: charger.categories())
    return ok({"categories": sorted(names)})


def _walking(ctx: Context) -> Callable[[int, int, str], None]:
    """Report a walk of every category onto the link, as a real fraction.

    A whole-charger read is the slowest thing this server does -- it is
    what a backup costs -- and it is the one long read that knows how many
    steps it has before it starts, so the browser gets a bar that means
    something rather than a sweep that only means "still going".
    """

    def walked(done: int, total: int, name: str) -> None:
        ctx.worker.progress(done / total if total else None, f"{name} ({done}/{total})")

    return walked


def get_properties(ctx: Context, req: Request) -> Response:
    """Properties, merged with the EDS catalog, optionally filtered."""
    category = req.param("category") or None
    pattern = req.param("q") or None
    name = f"Reading properties ({category})" if category else "Reading all properties"
    props = ctx.worker.run(
        name,
        lambda charger: properties.collect(
            charger, ctx.catalog, pattern, category, _walking(ctx)
        ),
    )
    return ok({"properties": [schema.property_json(p) for p in props]})


def get_logs(ctx: Context, req: Request) -> Response:
    """Read the charger's event log: its newest page, or back to ``since``.

    Without ``?since=`` this is one page, which is what the live follow
    needs and what opening the tab costs.  With it the log is paged
    backwards to that point -- the same walk ``alfenctl logs --since``
    does, and the same spellings ("today", "24h", "7d", "all") -- which
    takes as long as it takes, so it reports its progress as it goes.
    """
    since_spec = req.param("since").strip()
    try:
        asked = int(req.param("lines", "0") or 0) or LOG_PAGE_LINES
    except ValueError:
        asked = LOG_PAGE_LINES
    lines = max(1, min(LOG_PAGE_LINES, asked))

    if since_spec:
        try:
            cutoff = logs.parse_since(since_spec)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc

        def read_back(charger: AlfenCharger) -> list[Any]:
            def progress(state: logs.Download) -> None:
                ctx.worker.progress(None, f"{state.fetched} lines, page {state.pages}")

            return logs.download(
                charger, cutoff, lines_per_request=lines, on_progress=progress
            ).lines

        page = ctx.worker.run(f"Reading the event log since {since_spec}", read_back)
    else:

        def read(charger: AlfenCharger) -> list[Any]:
            return logs.parse_page(charger.fetch_log(0, lines))

        page = ctx.worker.run("Reading the event log", read)

    newest = max((ln.id for ln in page if ln.id is not None), default=None)
    ctx.live.log_last_id = newest if newest is not None else ctx.live.log_last_id
    return ok({"lines": [schema.log_json(line) for line in page]})


def get_firmware_available(ctx: Context, req: Request) -> Response:
    """List what Alfen publishes for this charger, newest first.

    The listing is an FTP round trip to Alfen and never touches the station,
    so it runs on this request's own thread rather than queueing behind
    whatever the charger is doing.  Only the charger's identity is needed,
    and the worker already has it.
    """
    from alfenctl.repo import RepositoryError, candidates, list_firmware

    info = ctx.worker.info or ctx.worker.run("Reading charger information", _identify)
    config = _repo_config(ctx)
    try:
        found = candidates(list_firmware(config), info, include_all=req.flag("all"))
    except RepositoryError as exc:
        raise ApiError(502, str(exc)) from None
    return ok(
        {
            "source": config.location,
            "family": info.family,
            "model": info.model,
            "firmware": info.firmware,
            "releases": [schema.firmware_json(c) for c in found],
        }
    )


def _identify(charger: AlfenCharger) -> Any:
    """Read the charger's identity (used when the worker has not yet)."""
    return charger.basic_info()


def _repo_config(ctx: Context) -> Any:
    """Return the firmware server to ask: Alfen's, or the config's ``[firmware]``."""
    from alfenctl.repo import RepoConfig

    return getattr(ctx.config, "firmware", None) or RepoConfig()


def get_jobs(ctx: Context, req: Request) -> Response:
    """Every job the worker still remembers."""
    return ok({"jobs": ctx.worker.jobs()})


# --- link control ------------------------------------------------------------------------


def post_station(ctx: Context, req: Request) -> Response:
    """Point the worker at a station (by config name, or by address)."""
    doc = req.json()
    from alfenctl.charger import DEFAULT_OLD_PASSWORD, DEFAULT_OLD_USER
    from alfenctl.discovery import Station

    name = str(doc.get("name") or "").strip()
    host = str(doc.get("host") or "").strip()
    username = doc.get("username")
    password = doc.get("password")
    port = doc.get("port")
    https = doc.get("https")

    entry = ctx.config.station(name) if (ctx.config is not None and name) else None
    if entry is not None:
        host = host or (entry.host or "")
        username = username if username is not None else entry.username
        password = password if password is not None else entry.password
        port = port if port is not None else entry.port
        https = (
            https
            if https is not None
            else (not entry.http if entry.http is not None else None)
        )
    if not host:
        raise ApiError(400, "no address for that station; give a host")
    if ctx.config is not None:
        username = username if username is not None else ctx.config.username
        password = password if password is not None else ctx.config.password
    station = Station(
        ip=host,
        port=int(port) if port else 443,
        https=True if https is None else bool(https),
        hostname=name,
    )
    ctx.worker.set_target(
        Target(
            station=station,
            username=str(username or DEFAULT_OLD_USER),
            password=str(password or DEFAULT_OLD_PASSWORD),
            label=name or host,
            debug=ctx.debug,
        )
    )
    ctx.live.forget()
    return ok({"link": ctx.worker.link_state()})


def post_link(ctx: Context, req: Request) -> Response:
    """Connect now, or hand the charger back."""
    action = str(req.json().get("action") or "").strip().lower()
    if action == "release":
        ctx.worker.set_poll(live=False)
        ctx.worker.release()
    elif action == "connect":
        ctx.worker.run("Connecting", lambda charger: None)
    else:
        raise ApiError(400, "action must be 'connect' or 'release'")
    return ok({"link": ctx.worker.link_state()})


def post_live(ctx: Context, req: Request) -> Response:
    """Turn the live refresh on or off, and set its interval.

    This is deliberately shared rather than per-browser: there is one
    charger connection, so there is one answer to "is it being polled".
    """
    doc = req.json()
    if "logs" in doc:
        ctx.live.follow_logs = bool(doc["logs"])
    ctx.worker.set_poll(
        live=bool(doc["enabled"]) if "enabled" in doc else None,
        interval=float(doc["interval"]) if doc.get("interval") else None,
    )
    return ok({"link": ctx.worker.link_state(), "followLogs": ctx.live.follow_logs})


def make_poll(ctx: Context) -> Callable[[AlfenCharger], None]:
    """Build the function the worker runs on every live refresh."""

    def poll(charger: AlfenCharger) -> None:
        snapshot = _read_status(ctx, charger)
        ctx.worker.events.publish("status", snapshot, sticky=True)
        if ctx.live.follow_logs:
            tail = logs.poll(charger, ctx.live.log_last_id)
            ctx.live.log_last_id = tail.last_id
            if tail.lines:
                ctx.worker.events.publish(
                    "log",
                    {
                        "lines": [schema.log_json(line) for line in tail.lines],
                        "missed": tail.missed,
                    },
                )

    return poll


# --- writes ------------------------------------------------------------------------------


def post_properties(ctx: Context, req: Request) -> Response:
    """Validate and write one or more properties, then read them back."""
    from alfenctl.values import coerce_input, merge

    writes = req.json().get("writes")
    if not isinstance(writes, list) or not writes:
        raise ApiError(400, "expected a non-empty 'writes' list")
    wanted: list[tuple[str, Any]] = []
    for item in writes:
        if not isinstance(item, dict) or "id" not in item:
            raise ApiError(400, "each write needs an 'id' and a 'value'")
        wanted.append((str(item["id"]), item.get("value")))

    def write(charger: AlfenCharger) -> dict[str, Any]:
        props, errors = properties.resolve(
            charger, ctx.catalog, [query for query, _ in wanted]
        )
        by_id = {p.id_str: p for p in props}
        payload: dict[tuple[int, int], tuple[Any, int | None]] = {}
        for query, raw in wanted:
            prop = by_id.get(query)
            if prop is None:
                errors.append(f"{query}: not found on this charger")
                continue
            if not prop.writable:
                errors.append(f"{query}: read-only")
                continue
            try:
                payload[prop.key] = (coerce_input(prop, raw), prop.data_type)
            except ValueError as exc:
                errors.append(str(exc))
        if errors:
            raise ApiError(400, "; ".join(errors))
        charger.write_properties(payload)
        after = charger.fetch_properties_by_ids(list(payload))
        return {
            "properties": [
                schema.property_json(merge(lp, ctx.catalog.get(lp.key))) for lp in after
            ]
        }

    label = wanted[0][0] if len(wanted) == 1 else f"{len(wanted)} properties"
    result = ctx.worker.run(f"Writing {label}", write)
    ctx.worker.events.publish("properties", result)
    return ok(result)


def _number(doc: dict[str, Any], name: str, unit: str) -> float | None:
    """Read one optional number from a request body."""
    raw = doc.get(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be a number of {unit}") from None


def _amps(doc: dict[str, Any], name: str) -> float | None:
    """Read one optional current from a request body."""
    return _number(doc, name, "amps")


def post_controls(ctx: Context, req: Request) -> Response:
    """Set a current limit or the display brightness.

    Everything named in the body goes in one write, so moving both sockets
    at once is one hold of the connection rather than two.  Only the sockets
    are named here: they are a list of their own rather than a field, and the
    rest of the body is checked against the field table.
    """
    doc = dict(req.json())
    sockets: dict[int, float] = {}
    for item in doc.pop("sockets", None) or []:
        if not isinstance(item, dict) or "number" not in item:
            raise ApiError(400, "each socket needs a 'number' and a current")
        amps = _amps(item, "maxCurrentA")
        if amps is not None:
            sockets[int(item["number"])] = amps
    settings = fields.from_document(controls.FIELDS, doc)
    if sockets:
        settings["sockets"] = sockets

    def write(charger: AlfenCharger) -> dict[str, Any]:
        return schema.controls_json(controls.apply(charger, settings)) or {}

    return ok({"controls": ctx.worker.run("Writing charger settings", write)})


def post_reboot(ctx: Context, req: Request) -> Response:
    """Restart the charger."""
    from alfenctl.upgrade import REBOOT_SETTLE_S

    def reboot(charger: AlfenCharger) -> None:
        time.sleep(REBOOT_SETTLE_S)  # let recent writes settle, as the app does
        charger.reboot(is_ahp=ctx.worker.is_ahp)

    ctx.worker.set_poll(live=False)
    ctx.worker.run("Rebooting the charger", reboot)
    ctx.worker.release()  # the session dies with the reboot; start clean after
    return ok({"message": "Reboot command sent; the charger is restarting."})


def post_time_sync(ctx: Context, req: Request) -> Response:
    """Set the charger's clock from this computer."""

    def sync(charger: AlfenCharger) -> dict[str, Any]:
        clock.sync(charger, is_ahp=ctx.worker.is_ahp)
        return schema.clock_json(clock.read(charger)) or {}

    return ok({"clock": ctx.worker.run("Setting the charger clock", sync)})


def post_license(ctx: Context, req: Request) -> Response:
    """Install a license key."""
    from alfenctl.license import (
        PROP_LICENSE_KEY,
        LicenseKeyError,
        normalize_license_key,
        read_license,
    )

    raw = str(req.json().get("key") or "")
    try:
        key = normalize_license_key(raw)
    except LicenseKeyError as exc:
        raise ApiError(400, str(exc)) from None

    def install(charger: AlfenCharger) -> dict[str, Any]:
        charger.write_properties({PROP_LICENSE_KEY: (key, None)})
        return schema.license_json(read_license(charger), charger.basic_info()) or {}

    return ok(
        {
            "key": key,
            "license": ctx.worker.run("Installing the license key", install),
            "message": (
                "License key set. The charger reboots on its own to install "
                "any new feature."
            ),
        }
    )


def post_cloud_login(ctx: Context, req: Request) -> Response:
    """Run Alfen's hosted sign-in for the UI: start it, or finish it.

    ``{"action":"start","origin":"<page origin>"}`` returns the URL to open
    and whether it is a loopback sign-in.  When the page is served from a
    ``http://localhost:<port>`` Alfen accepts, the redirect comes straight back
    to the app and the code is read with nothing to paste; otherwise the reply
    says ``loopback: false`` and the page offers the paste field.  The user
    types their Alfen username and password on Alfen's own page, never here.
    ``{"action":"finish","redirected":"<url>"}`` trades the code the browser
    was sent back for a token, caches it beside the config (0600, tokens
    only, the same cache the CLI's ``cloud login`` writes), and reports whose
    account it is.  The token then backs the lookup with nothing to paste.
    ``{"action":"logout"}`` deletes that cache, so the page can sign out and
    let a different account sign in.
    """
    from alfenctl import cloud
    from alfenctl.config import default_config_dir

    doc = req.json()
    action = str(doc.get("action") or "").strip().lower()
    if action == "start":
        origin = str(doc.get("origin") or "").strip() or None
        url, loopback = ctx.cloud_logins.begin(origin)
        return ok({"url": url, "loopback": loopback})
    if action == "logout":
        removed = cloud.clear_cached_token(default_config_dir())
        return ok({"signedOut": True, "removed": removed})
    if action != "finish":
        raise ApiError(400, "action must be 'start', 'finish' or 'logout'")

    redirected = str(doc.get("redirected") or "").strip()
    if not redirected:
        raise ApiError(400, "paste the address the browser was redirected to")
    client = cloud.make_client()
    try:
        try:
            token = ctx.cloud_logins.complete(client, redirected)
        except cloud.CloudError as exc:
            raise ApiError(400, str(exc)) from None
        cloud.save_cached_token(default_config_dir(), token)
        who = _cloud_try(
            lambda: cloud.MyEveClient(
                token.access_token, client=client
            ).authenticated_user()
        )
    finally:
        client.close()
    return ok({"account": _cloud_account_name(who)})


def _cloud_account_name(user: Any) -> str | None:
    """Pull a display name (or the uuid) out of a getAuthenticatedUser reply."""
    if not isinstance(user, dict):
        return None
    profile = user.get("profileInformation") or {}
    name = " ".join(p for p in (profile.get("firstName"), profile.get("lastName")) if p)
    return name or user.get("uuid")


def post_cloud(ctx: Context, req: Request) -> Response:
    """Look a station up on Alfen's servers, for the owner's information.

    Reads the account, the warranty, and the license key Alfen has on file
    (which the License card can then install through the ordinary write
    route).  The token is whichever the page supplied, or -- once the user
    has signed in through ``/api/cloud/login`` -- the cached one, renewed
    from its refresh half if it has expired.  A supplied token is never
    stored; the Alfen password is never involved.
    """
    from alfenctl import cloud
    from alfenctl.config import default_config_dir
    from alfenctl.license import LicenseKeyError, normalize_license_key, read_license

    body_token = str(req.json().get("token") or "").strip()
    config_dir = default_config_dir()
    token = (
        cloud.Token(access_token=body_token)
        if body_token
        else cloud.token_from_sources(config_dir=config_dir)
    )
    if token is None:
        raise ApiError(400, "sign in to Alfen first, or supply an access token")

    def read(charger: AlfenCharger) -> dict[str, Any]:
        info = charger.basic_info()
        current = read_license(charger).license_key
        return {
            "identifier": info.object_id,
            "sockets": info.sockets or 1,
            "installed": current,
        }

    local = ctx.worker.run("Reading station identity", read)

    def _norm(raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            return normalize_license_key(raw)
        except LicenseKeyError:
            # An odd key from either side should dim the row, not fail the read.
            return raw

    client = cloud.make_client()
    try:
        if token.expired and token.refresh_token:
            try:
                token = cloud.refresh_token(client, token)
            except cloud.CloudError as exc:
                raise ApiError(401, str(exc)) from None
            if not body_token:
                cloud.save_cached_token(config_dir, token)
        myeve = cloud.MyEveClient(token.access_token, client=client)
        user = _cloud_try(lambda: myeve.authenticated_user())
        warranty = _cloud_try(lambda: myeve.warranty(local["identifier"]))
        recorded = _cloud_try(lambda: myeve.last_created(local["identifier"]))
        defaults = _cloud_try(
            lambda: myeve.factory_defaults(local["identifier"], local["sockets"])
        )
        try:
            registered = myeve.license_key(local["identifier"], local["sockets"])
        except cloud.CloudError as exc:
            raise ApiError(502, str(exc)) from None
    finally:
        client.close()

    return ok(
        schema.cloud_json(
            local["identifier"],
            local["sockets"],
            user=user,
            warranty=warranty,
            registered_key=_norm(registered),
            installed_key=_norm(local["installed"]),
            recorded=recorded if isinstance(recorded, dict) else None,
            defaults=_decorate_defaults(
                ctx, defaults if isinstance(defaults, list) else []
            ),
        )
    )


def _decorate_defaults(
    ctx: Context, defaults: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Name each factory-default property, the way the property views do.

    The server hands back bare ``id``/``value`` pairs; this adds the EDS
    catalog's title (or the program's glossary where the EDS is silent), so
    the page shows the manufacturer's profile as properties rather than a
    column of register numbers.  Sorted by id, so the list is stable.
    """
    from alfenctl.glossary import title as glossary_title
    from alfenctl.transport import parse_prop_id

    catalog = ctx.catalog
    rows: list[dict[str, Any]] = []
    for entry in defaults:
        prop_id = str(entry.get("id") or "")
        key = parse_prop_id(prop_id)
        described = catalog.get(key) if key else None
        title = (described.title if described else "") or (
            glossary_title(key) if key else ""
        )
        rows.append(
            {
                "id": prop_id,
                "name": described.name if described else "",
                "title": title,
                "value": entry.get("value"),
            }
        )
    rows.sort(key=lambda row: row["id"])
    return rows


def _cloud_try(call: Callable[[], Any]) -> Any:
    """Run one cloud sub-query, returning None on the failures we can survive.

    The lookup gathers several independent answers; one the account is not
    entitled to should dim a field, not fail the whole request.
    """
    from alfenctl.cloud import CloudError

    try:
        return call()
    except CloudError:
        return None


def _spool(req: Request, suffix: str) -> Path:
    """Write an uploaded body to a temporary file for the modules that want a path."""
    return spool(
        req,
        max_bytes=MAX_UPLOAD_BYTES,
        prefix="alfenctl-ui-",
        suffix=suffix,
        too_large="that file is far larger than anything a charger takes",
    )


def post_logo(ctx: Context, req: Request) -> Response:
    """Convert and upload a splash-screen logo, as a job.

    A station with no screen takes the transfer and does nothing with it, so
    it is refused here rather than run: the page knows from the dashboard
    document not to offer the control, and this is the guard behind that.
    ``?force=1`` sends it regardless -- what a charger really does with one
    is the charger's to say -- and that is what ``alfenctl logo --force`` is.
    """
    from alfenctl.logo import LOGO_MARGIN, build_package, read_display

    path = _spool(req, ".png")
    try:
        margin = int(req.param("margin", str(LOGO_MARGIN)) or LOGO_MARGIN)
    except ValueError:
        margin = LOGO_MARGIN

    if not req.flag("force"):
        display = ctx.worker.run("Reading the display", read_display)
        if not display.present:
            discard(path)
            raise ApiError(
                400,
                "this station has no display, so a logo would be transferred "
                "and never shown; `alfenctl logo --force` sends one anyway",
            )

    def run(charger: AlfenCharger, job: Job) -> None:
        job.report(0.0, "Converting the image", force=True)
        try:
            package, kind, box = build_package(charger, path, margin=margin)
            job.report(0.1, f"Built a {kind.upper()} package for {box[0]}x{box[1]}")
            send_image(
                charger,
                package,
                report=upgrade_reporter(job, start=0.1),
                label="Uploading the logo",
                is_ahp=kind == "tvf",
            )
        finally:
            discard(path)
        job.result = {
            "kind": kind,
            "bytes": len(package),
            "display": f"{box[0]}x{box[1]}",
            "note": (
                "HTTP 200 only means the transfer was accepted. A charger "
                "without the Personalized display feature keeps its default "
                "logo and says so in its log."
            ),
        }
        job.report(1.0, "Logo uploaded", force=True)

    job = ctx.worker.start_job(f"Uploading logo {path.name}", run)
    return ok({"job": job.as_dict()}, status=202)


def post_firmware(ctx: Context, req: Request) -> Response:
    """Check, upload and install an uploaded firmware image, as a job."""
    path = _spool(req, ".fwi")
    force = req.flag("force")

    def run(charger: AlfenCharger, job: Job) -> None:
        _install_firmware(charger, job, path, force=force)

    job = ctx.worker.start_job(f"Firmware upgrade ({path.name})", run)
    return ok({"job": job.as_dict()}, status=202)


def post_firmware_release(ctx: Context, req: Request) -> Response:
    """Download one of Alfen's published releases and install it, as a job.

    The same job as an uploaded file, with the download in front of it: the
    charger is not touched until the image is on this machine, so a slow FTP
    transfer does not sit on the connection.
    """
    from alfenctl.repo import RemoteFirmware, RepositoryError, download, list_firmware

    doc = req.json()
    wanted = str(doc.get("name") or "").strip()
    if not wanted:
        raise ApiError(400, "name the release to install")
    force = bool(doc.get("force"))
    config = _repo_config(ctx)
    cache_dir = Path(str(doc["cacheDir"])).expanduser() if doc.get("cacheDir") else None

    def run(charger: AlfenCharger, job: Job) -> None:
        job.report(0.0, f"Looking for {wanted} on {config.location}", force=True)
        try:
            published = list_firmware(config)
        except RepositoryError as exc:
            raise RuntimeError(str(exc)) from None
        match: RemoteFirmware | None = next(
            (fw for fw in published if fw.name == wanted), None
        )
        if match is None:
            raise RuntimeError(f"{config.location} no longer publishes {wanted}")

        family = (ctx.worker.info.family if ctx.worker.info else "") or ""
        try:
            path = download(
                match,
                family,
                config=config,
                cache_dir=cache_dir,
                report=download_reporter(job),
            )
        except RepositoryError as exc:
            raise RuntimeError(str(exc)) from None
        job.report(DOWNLOAD_SHARE_OF_JOB, f"Downloaded {path.name}", force=True)
        # The image is cached deliberately, so unlike an upload it is kept.
        _install_firmware(charger, job, path, force=force, keep=True)

    job = ctx.worker.start_job(f"Firmware upgrade ({wanted})", run)
    return ok({"job": job.as_dict()}, status=202)


def _install_firmware(
    charger: AlfenCharger, job: Job, path: Path, *, force: bool, keep: bool = False
) -> None:
    """Check one image against this charger, then upload, install and commit it.

    The upgrade itself is :func:`alfenctl.upgrade.install`, the same call the
    CLI makes; all that differs is where its progress goes.
    """
    from alfenctl.firmware import FirmwareFile, check_compatibility

    job.report(message="Reading the firmware file", force=True)
    try:
        image = FirmwareFile.load(path)
    finally:
        if not keep:  # megabytes; do not leave it in /tmp
            discard(path)
    info = charger.basic_info()
    result = check_compatibility(info.family, info.firmware_version, image)
    job.result = {
        "notes": list(result.notes),
        "warnings": list(result.warnings),
        "errors": list(result.errors),
    }
    if not result.ok and not force:
        raise ApiError(400, "; ".join(result.errors) or "incompatible firmware")

    report = upgrade_reporter(job, start=job.progress or 0.0)
    install(charger, image.data, report=report)
    if report.warnings:
        job.result["commitWarning"] = "; ".join(report.warnings)
    after = charger.basic_info()
    job.result |= {"from": info.firmware, "to": after.firmware}
    job.report(1.0, f"Firmware {info.firmware} -> {after.firmware}", force=True)


# --- reads: the panels behind the other tabs ---------------------------------------------


def get_loadbalancing(ctx: Context, req: Request) -> Response:
    """Load balancing and solar charging, as the Charging tab reads them."""
    from alfenctl import loadbalancing

    state = ctx.worker.run(
        "Reading load balancing", lambda charger: loadbalancing.read(charger)
    )
    return ok({"loadbalancing": schema.loadbalancing_json(state)})


def get_authorization(ctx: Context, req: Request) -> Response:
    """Who may start a session, as the Access tab reads it."""
    from alfenctl import authorization

    state = ctx.worker.run(
        "Reading authorization", lambda charger: authorization.read(charger)
    )
    return ok({"authorization": schema.authorization_json(state)})


def get_ocpp(ctx: Context, req: Request) -> Response:
    """Read the backoffice connection, as the Backoffice tab shows it."""
    from alfenctl import ocpp

    state = ctx.worker.run("Reading the backoffice", lambda charger: ocpp.read(charger))
    return ok({"ocpp": schema.ocpp_json(state)})


def get_tags(ctx: Context, req: Request) -> Response:
    """Read the whole RFID whitelist (it pages, so it can take a while)."""
    from alfenctl import whitelist

    def read(charger: AlfenCharger) -> dict[str, Any]:
        tags = whitelist.download(charger)
        return {"tags": [schema.tag_json(t) for t in tags]}

    return ok(ctx.worker.run("Reading the whitelist", read))


def get_master_tag(ctx: Context, req: Request) -> Response:
    """Read the master tag: one RFID tag that always authorises."""
    from alfenctl import master_tag

    state = ctx.worker.run("Reading the master tag", master_tag.read)
    return ok({"masterTag": schema.master_tag_json(state)})


def get_connectivity(ctx: Context, req: Request) -> Response:
    """Where the charger is reachable, per interface."""
    from alfenctl import connectivity

    state = ctx.worker.run(
        "Reading the interfaces", lambda charger: connectivity.read(charger)
    )
    return ok({"connectivity": schema.connectivity_json(state)})


def get_wifi_scan(ctx: Context, req: Request) -> Response:
    """Scan with the charger's own radio, switching it on first if asked.

    The radio takes seconds to come up, so enabling is done under the same
    worker task as the scan and the reply says which happened.
    """
    from alfenctl import connectivity, wifi

    def scan(charger: AlfenCharger) -> dict[str, Any]:
        state = connectivity.read(charger)
        enabled = False
        obstacle = state.scan_obstacle()
        if obstacle and req.flag("enable") and state.wifi_hardware is not False:
            connectivity.enable(charger)
            state = connectivity.wait_for_radio(charger)
            enabled = True
            obstacle = state.scan_obstacle()
        if obstacle:
            return {"networks": [], "enabled": enabled, "note": obstacle}
        reply = wifi.parse_reply(charger.wifi_scan())
        return {
            "networks": [schema.wifi_network_json(n) for n in reply.networks],
            "enabled": enabled,
            "note": reply.summary(),
        }

    return ok(ctx.worker.run("Scanning for Wi-Fi networks", scan))


def get_meter_test(ctx: Context, req: Request) -> Response:
    """Read live per-phase readings from the external Modbus meter."""
    from alfenctl import meter_test

    def read(charger: AlfenCharger) -> dict[str, Any]:
        values = charger.properties(meter_test.CATEGORY)
        return {
            "readings": [
                {"label": m.label, "value": m.value, "unit": m.unit}
                for m in meter_test.read(values)
            ]
        }

    return ok(ctx.worker.run("Reading the meter test", read))


def get_meter_map(ctx: Context, req: Request) -> Response:
    """Read the custom Modbus register map the charger currently holds.

    A charger that publishes none is a charger reading a meter it knows,
    which is the ordinary case, so it renders as an empty map rather than
    the error the CLI prints.
    """
    from alfenctl import meter_map
    from alfenctl.meter_map import MeterMapError

    def read(charger: AlfenCharger):
        try:
            return meter_map.read(charger)
        except MeterMapError:
            return meter_map.RegisterMap(entries=[], capacity=None)

    regmap = ctx.worker.run("Reading the meter map", read)
    return ok({"meterMap": schema.meter_map_json(regmap)})


def get_doctor(ctx: Context, req: Request) -> Response:
    """Run one read-only pass over everything the vendor app warns about."""
    from alfenctl import doctor

    report = ctx.worker.run("Checking the charger over", doctor.run)
    return ok({"doctor": schema.doctor_json(report)})


def get_profiles(ctx: Context, req: Request) -> Response:
    """Read the installed OCPP charging profiles, with their schedules."""
    from alfenctl import charging_profiles

    def read(charger: AlfenCharger) -> dict[str, Any]:
        try:
            ids = charging_profiles.parse_ids(charger.fetch_charging_profile_ids().text)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == HTTP_NOT_FOUND:
                return {"supported": False, "profiles": []}
            raise
        profiles: list[dict[str, Any]] = []
        for pid in ids:
            body = charger.fetch_charging_profile(pid).text
            profiles.extend(
                schema.charging_profile_json(p)
                for p in charging_profiles.parse_profiles(body)
            )
        return {"supported": True, "profiles": profiles}

    return ok(ctx.worker.run("Reading charging profiles", read))


def get_direct_start(ctx: Context, req: Request) -> Response:
    """Read the per-socket override of an installed charging profile."""
    from alfenctl import charging_profiles

    state = ctx.worker.run(
        "Reading the profile override", charging_profiles.read_direct_start
    )
    return ok({"directStart": schema.direct_start_json(state)})


def get_scn(ctx: Context, req: Request) -> Response:
    """SCN membership, and (with ?peers=1) the LAN's other members."""
    from alfenctl import scn

    def read(charger: AlfenCharger) -> dict[str, Any]:
        membership = scn.read_membership(charger)
        peers = None
        if req.flag("peers") and membership.in_network:
            peers = _scn_probe_peers(ctx, charger)
        return {"scn": schema.scn_json(membership, peers)}

    return ok(ctx.worker.run("Reading SCN membership", read))


class _PeerWarnings(Reporter):
    """Puts a skipped peer's warning on the event stream, not the server's log.

    The CLI prints these to its own stderr; here they belong in front of the
    person who pressed the button.  ``progress`` is throttled, so a burst of
    unreachable stations shows the last of them rather than all -- which is
    what the pill has room for anyway.
    """

    def __init__(self, worker: StationWorker) -> None:
        """Report onto ``worker``'s current-operation note."""
        self.worker = worker

    def warn(self, message: str) -> None:
        """Show one skipped peer as the running read's note."""
        self.worker.progress(None, message)


def _scn_probe_peers(ctx: Context, charger: AlfenCharger) -> list[Any]:
    """Probe the LAN for the other chargers in this charger's network.

    The CLI opens one connection per peer; the worker owns ours, so this
    reaches around it the same way ``alfenctl scn --peers`` does.
    """
    found = scn.probe_peers(
        ctx.discover_time,
        charger.station.ip,
        charger.username,
        charger.password,
        debug=ctx.debug,
        reporter=_PeerWarnings(ctx.worker),
    )
    return [peer for _station, peer in found]


def get_transactions(ctx: Context, req: Request) -> Response:
    """Read charging sessions from the transaction database, with summaries.

    The whole database is read every time (there is no way to ask for less)
    and paging it takes seconds on a station with a year of sessions, so
    every grouping the UI offers is computed from that one download and
    sent with it.  Switching from months to tags is then a click rather
    than another walk of the charger, and the progress the read reports on
    the way (see :meth:`StationWorker.progress`) is what the browser draws
    while it waits.

    ``?summary=`` remains: it names *one* grouping and puts it under
    ``summary``, which is what the CLI-shaped callers ask for.
    """
    from alfenctl import transactions

    socket = req.param("socket")
    socket_n = int(socket) if socket.isdigit() else None
    grouping = req.param("summary") or None
    if grouping is not None and grouping not in transactions.GROUPINGS:
        known = ", ".join(sorted(transactions.GROUPINGS))
        raise ApiError(400, f"summary is one of {known}")

    def read(charger: AlfenCharger) -> dict[str, Any]:
        def progress(state: transactions.Download) -> None:
            ctx.worker.progress(
                None, f"{len(state.records)} records, page {state.pages}"
            )

        result = transactions.download(charger, on_progress=progress)
        rows = transactions.sessions(result.records)
        if socket_n is not None:
            rows = [s for s in rows if s.socket == socket_n]
        totals = transactions.total(rows)
        doc: dict[str, Any] = {
            "truncated": result.truncated,
            "sessions": [schema.session_json(s) for s in rows],
            "summaries": {
                name: [
                    schema.totals_json(t)
                    for t in transactions.summarise(rows, transactions.GROUPINGS[name])
                ]
                for name in transactions.GROUPINGS
            },
            "total": schema.totals_json(totals),
        }
        if grouping is not None:
            doc["summary"] = doc["summaries"][grouping]
        return doc

    return ok(ctx.worker.run("Reading charging sessions", read))


def get_secrets(ctx: Context, req: Request) -> Response:
    """List the write-only secrets that can be installed (no charger round trip)."""
    from alfenctl import secret

    return ok({"secrets": [schema.secret_json(s) for s in secret.SECRETS]})


def get_presets(ctx: Context, req: Request) -> Response:
    """List what Alfen publishes as presets, beside its firmware."""
    from alfenctl.repo import list_presets

    presets = list_presets(_repo_config(ctx))
    return ok(
        {
            "presets": [schema.preset_json(p) for p in presets],
            "backofficeCount": sum(1 for p in presets if p.is_backoffice),
        }
    )


def _match_presets(config: Any, wanted: str) -> list[Any]:
    """Every published preset matching what the caller named.

    The same rule ``post_preset`` applies, so what a preview shows is what
    an apply would write: an exact label or filename first, then anything
    the name is a substring of.
    """
    from alfenctl.repo import list_presets

    return [
        p
        for p in list_presets(config)
        if wanted in (p.label.lower(), p.name.lower()) or wanted in p.label.lower()
    ]


def get_preset(ctx: Context, req: Request) -> Response:
    """Show what a preset holds, without writing any of it to the charger.

    Applying one used to be the only way to find out what was in it, which
    for something that clears the current backoffice settings and reboots
    is a poor way round.  This downloads the same file the apply would and
    says what it would do: the properties a settings preset writes, the
    registers a meter map claims, and -- for a backoffice preset, which is
    a signed blob nothing here can read -- how big it is and what applying
    it costs.

    No charger is touched, so it does not go through the worker: this is a
    read of Alfen's own server, like the preset list beside it.
    """
    from alfenctl import meter_map as meter_map_mod, settings as settings_mod
    from alfenctl.charger import parse_prop_id
    from alfenctl.glossary import title as glossary_title
    from alfenctl.repo import fetch_preset, fetch_preset_bytes

    wanted = (req.param("name") or "").strip().lower()
    if not wanted:
        raise ApiError(400, "name the preset to show")
    config = _repo_config(ctx)
    matches = _match_presets(config, wanted)
    if not matches:
        raise ApiError(404, f"no preset matches {wanted!r}")
    preset = matches[0]
    doc: dict[str, Any] = {"preset": schema.preset_json(preset)}

    if preset.is_backoffice:
        blob = fetch_preset_bytes(preset, config)
        doc["kind"] = "backoffice"
        doc["bytes"] = len(blob)
        doc["note"] = (
            "A signed blob the charger unpacks itself -- there is nothing "
            "here to read. Applying it clears the current backoffice "
            "settings, uploads this through the firmware channel, and needs "
            "a reboot afterwards."
        )
        return ok(doc)

    text = fetch_preset(preset, config)
    if preset.is_meter_map:
        register_map = meter_map_mod.parse_json(text)
        doc["kind"] = "meter-map"
        doc["entries"] = [
            {
                "measurand": entry.measurand,
                "register": entry.register,
                "dataType": entry.data_type,
                "factor": entry.factor,
            }
            for entry in register_map.entries
        ]
        return ok(doc)

    doc["kind"] = "settings"
    rows = []
    for entry in settings_mod.parse(text).as_entries():
        key = parse_prop_id(str(entry["id"]))
        described = ctx.catalog.get(key) if key else None
        rows.append(
            {
                "id": entry["id"],
                "value": entry["value"],
                "name": described.name if described else "",
                "title": (described.title if described else "")
                or (glossary_title(key) if key else ""),
            }
        )
    doc["entries"] = rows
    return ok(doc)


def get_console_commands(ctx: Context, req: Request) -> Response:
    """List what the charger's console is known to do (from the CLI's table).

    The CLI and web console share both the command catalog and its note
    distinguishing client dispatch from firmware support and SSA access.
    """
    return ok(
        {
            "commands": [
                schema.console_command_json(*row) for row in console.CONSOLE_COMMANDS
            ],
            "note": console.CONSOLE_UNKNOWN_NOTE,
        }
    )


# --- writes: the same panels, changed ------------------------------------------------------


def _flags(doc: dict[str, Any], *names: str) -> dict[str, bool]:
    """Read the optional booleans the body named, keeping only those."""
    out: dict[str, bool] = {}
    for name in names:
        if name in doc and doc[name] is not None:
            value = doc[name]
            if not isinstance(value, bool):
                raise ApiError(400, f"{name} must be true or false")
            out[name] = value
    return out


def _opt_int(doc: dict[str, Any], name: str) -> int | None:
    """One optional integer from a request body."""
    raw = doc.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be a whole number") from None


def _opt_text(doc: dict[str, Any], name: str) -> str | None:
    """One optional string from a request body (empty means: write it empty)."""
    if name not in doc or doc[name] is None:
        return None
    value = doc[name]
    if not isinstance(value, str):
        raise ApiError(400, f"{name} must be a string")
    return value


def post_loadbalancing(ctx: Context, req: Request) -> Response:
    """Write the load-balancing and solar settings that were named.

    The body names fields the way the field table does, so nothing here lists
    them: an unknown key, a read-only one, and a value out of range are all
    refused by the table, in the same words the command line would use.
    """
    from alfenctl import loadbalancing

    doc = dict(req.json())
    boost = doc.pop("solarBoost", None)
    if boost is not None and not isinstance(boost, dict):
        raise ApiError(400, "solarBoost must map a socket number to true or false")
    settings = fields.from_document(loadbalancing.FIELDS, doc)
    if boost:
        settings["solar_boost"] = {int(k): bool(v) for k, v in boost.items()}

    def write(charger: AlfenCharger) -> dict[str, Any]:
        after = loadbalancing.apply(charger, settings)
        return schema.loadbalancing_json(after) or {}

    return ok({"loadbalancing": ctx.worker.run("Writing load balancing", write)})


def post_authorization(ctx: Context, req: Request) -> Response:
    """Write the authorization settings that were named."""
    from alfenctl import authorization

    settings = fields.from_document(authorization.FIELDS, req.json())

    def write(charger: AlfenCharger) -> dict[str, Any]:
        after = authorization.apply(charger, settings)
        return schema.authorization_json(after) or {}

    return ok({"authorization": ctx.worker.run("Writing authorization", write)})


def post_ocpp(ctx: Context, req: Request) -> Response:
    """Write the backoffice connection settings that were named."""
    from alfenctl import ocpp

    settings = fields.from_document(ocpp.FIELDS, req.json())

    def write(charger: AlfenCharger) -> dict[str, Any]:
        return schema.ocpp_json(ocpp.apply(charger, settings)) or {}

    return ok({"ocpp": ctx.worker.run("Writing the backoffice settings", write)})


def post_tags(ctx: Context, req: Request) -> Response:
    """Edit the whitelist: add, upsert, remove, clear, or start learn mode."""
    from alfenctl import whitelist

    doc = req.json()
    action = str(doc.get("action") or "")
    tags = doc.get("tags")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        if action in ("add", "remove"):
            raise ApiError(400, "tags must be a list of tag ids")
        tags = []

    def write(charger: AlfenCharger) -> dict[str, Any]:
        if action == "add":
            status = doc.get("status", whitelist.STATUS_ACTIVE)
            expires = doc.get("expires") or None
            for tag in tags:
                whitelist.upsert(
                    charger,
                    tag,
                    parent=doc.get("parent") or "",
                    status=status,
                    expires=expires,
                )
        elif action == "remove":
            for tag in tags:
                whitelist.remove(charger, tag)
        elif action == "clear":
            whitelist.clear(charger)
        elif action == "learn":
            whitelist.start_add_mode(charger)
        else:
            raise ApiError(400, "action is add, remove, clear or learn")
        return {
            "tags": [
                schema.tag_json(t)
                for t in whitelist.download(charger, max_tags=MAX_TAG_REREAD)
            ]
        }

    label = {"clear": "Clearing the whitelist", "learn": "Starting tag learn mode"}.get(
        action, f"{action.capitalize()}ing tag(s)"
    )
    return ok(ctx.worker.run(label, write))


# Re-reading the whole whitelist after every edit would page through the
# sparse list again; this many are plenty to confirm what was written.
MAX_TAG_REREAD = 256


def post_master_tag(ctx: Context, req: Request) -> Response:
    """Set or clear the master tag."""
    from alfenctl import master_tag

    doc = req.json()
    tag = _opt_text(doc, "tag")
    enabled = doc.get("enabled")
    if tag is None and enabled is None:
        raise ApiError(400, "name a tag, or an enabled flag, or both")

    def write(charger: AlfenCharger) -> dict[str, Any]:
        if tag == "":
            master_tag.clear(charger)
        elif tag is not None:
            master_tag.set_tag(
                charger, tag, enabled=True if enabled is None else bool(enabled)
            )
        return schema.master_tag_json(master_tag.read(charger)) or {}

    return ok({"masterTag": ctx.worker.run("Writing the master tag", write)})


def post_wifi(ctx: Context, req: Request) -> Response:
    """Join a network, or switch the radio on or off, or run its access point."""
    from alfenctl import connectivity
    from alfenctl.connectivity import ConnectivityError

    doc = req.json()
    action = str(doc.get("action") or "")
    ssid = _opt_text(doc, "ssid")
    psk = _opt_text(doc, "psk")
    security = _opt_int(doc, "security")

    def write(charger: AlfenCharger) -> dict[str, Any]:
        try:
            if action == "connect":
                if not ssid:
                    raise ApiError(400, "name the network to join")
                after = connectivity.connect(charger, ssid, psk, security=security)
            elif action == "enable":
                after = connectivity.enable(charger)
            elif action == "disconnect":
                after = connectivity.disconnect(charger)
            elif action == "ap":
                enabled = doc.get("enabled")
                after = connectivity.set_access_point(
                    charger,
                    enabled=None if enabled is None else bool(enabled),
                    start=None,
                )
            else:
                raise ApiError(400, "action is connect, enable, disconnect or ap")
        except ConnectivityError as exc:
            raise ApiError(400, str(exc)) from None
        return schema.connectivity_json(after) or {}

    label = {"connect": f"Joining {ssid}", "ap": "Switching the access point"}.get(
        action, f"Wi-Fi {action}"
    )
    return ok({"connectivity": ctx.worker.run(label, write)})


def post_meter_map(ctx: Context, req: Request) -> Response:
    """Apply a register map uploaded as one of Alfen's JSON files."""
    from alfenctl import meter_map
    from alfenctl.meter_map import MeterMapError

    if not req.body:
        raise ApiError(400, "no file content was uploaded")
    try:
        wanted = meter_map.parse_json(req.body.decode("utf-8", "replace"))
    except MeterMapError as exc:
        raise ApiError(400, str(exc)) from None

    def write(charger: AlfenCharger) -> dict[str, Any]:
        try:
            current = meter_map.read(charger)
            meter_map.apply(
                charger, wanted, capacity=current.capacity or len(wanted.entries)
            )
        except MeterMapError as exc:
            raise ApiError(400, str(exc)) from None
        return schema.meter_map_json(meter_map.read(charger)) or {}

    return ok({"meterMap": ctx.worker.run("Writing the meter map", write)})


def post_profiles(ctx: Context, req: Request) -> Response:
    """Install the UK default profile, or clear one or all."""
    from alfenctl import charging_profiles

    doc = req.json()
    action = str(doc.get("action") or "")

    def write(charger: AlfenCharger) -> dict[str, Any]:
        if action == "install-uk":
            charger.add_charging_profile(charging_profiles.uk_default_profile())
            return {"message": "UK Smart Charging default profile installed."}
        if action == "clear":
            target = doc.get("id", charging_profiles.CLEAR_ALL)
            charger.clear_charging_profile(target)
            return {"message": f"Cleared charging profile {target}."}
        raise ApiError(400, "action is install-uk or clear")

    return ok(ctx.worker.run("Writing charging profiles", write))


def post_direct_start(ctx: Context, req: Request) -> Response:
    """Let a socket start charging despite an installed profile."""
    from alfenctl import charging_profiles
    from alfenctl.charging_profiles import ChargingProfileError

    doc = req.json()
    sockets = doc.get("sockets")
    if not isinstance(sockets, list):
        raise ApiError(400, "sockets must be a list of socket numbers")

    def write(charger: AlfenCharger) -> dict[str, Any]:
        state = charging_profiles.read_direct_start(charger)
        try:
            after = charging_profiles.set_direct_start(
                charger,
                sockets={int(n): bool(doc.get("direct")) for n in sockets},
                random_delay_s=_opt_int(doc, "randomDelayS"),
                state=state,
            )
        except ChargingProfileError as exc:
            raise ApiError(400, str(exc)) from None
        return schema.direct_start_json(after) or {}

    return ok({"directStart": ctx.worker.run("Writing the profile override", write)})


def post_scn(ctx: Context, req: Request) -> Response:
    """Create, join or leave a Smart Charging Network (the charger reboots)."""
    from alfenctl import scn

    doc = req.json()
    action = str(doc.get("action") or "")
    name = _opt_text(doc, "name")

    def write(charger: AlfenCharger) -> dict[str, Any]:
        info = charger.basic_info()
        membership = scn.read_membership(charger)
        if action == "create":
            if membership.in_network:
                raise ApiError(
                    400,
                    f"already a member of '{membership.name}'; leave it first",
                )
            assert name is not None
            settings = scn.ScnSettings(
                alternating_period_s=_opt_int(doc, "alternatingPeriodS")
                or scn.DEFAULT_ALTERNATING_PERIOD_S,
                total_current_a=_number(doc, "totalCurrentA", "amps")
                or scn.DEFAULT_TOTAL_CURRENT_A,
                socket_safe_current_a=_number(doc, "socketSafeCurrentA", "amps")
                or scn.DEFAULT_SOCKET_SAFE_CURRENT_A,
                total_safe_current_a=_number(doc, "totalSafeCurrentA", "amps")
                or scn.DEFAULT_TOTAL_SAFE_CURRENT_A,
            )
            charger.write_properties(
                scn.create_writes(scn.validate_name(name), info.sockets or 1, settings)
            )
            _reboot_after_scn(ctx, charger, info)
            return {"message": f"Created '{name}'; the charger is rebooting."}
        if action == "join":
            if membership.in_network:
                raise ApiError(
                    400,
                    f"already a member of '{membership.name}'; leave it first",
                )
            assert name is not None
            members = [
                p
                for p in _scn_probe_peers(ctx, charger)
                if p.membership.name.strip().lower() == name.strip().lower()
            ]
            if not members:
                raise ApiError(
                    400,
                    f"no existing members of '{name}' found on the LAN; "
                    "create the network first",
                )
            members.sort(key=lambda p: p.membership.socket_id)
            reference = members[0]
            own_sockets = info.sockets or 1
            new_id = scn.next_socket_id(members)
            new_total = sum(p.own_sockets for p in members) + own_sockets
            charger.write_properties(
                scn.join_writes(
                    scn.validate_name(name),
                    new_id,
                    new_total,
                    reference.membership.settings,
                )
            )
            _reboot_after_scn(ctx, charger, info)
            return {
                "message": f"Joined '{name}' as socket {new_id}; the charger is "
                "rebooting."
            }
        if action == "leave":
            if not membership.in_network:
                raise ApiError(400, "not a member of a Smart Charging Network")
            charger.write_properties(scn.leave_writes())
            return {"message": "Removed from the network."}
        raise ApiError(400, "action is create, join or leave")

    return ok(ctx.worker.run(f"SCN {action}", write))


def _reboot_after_scn(ctx: Context, charger: AlfenCharger, info: Any) -> None:
    """Reboot the charger a membership change asked for, without waiting."""
    from alfenctl.upgrade import REBOOT_SETTLE_S

    time.sleep(REBOOT_SETTLE_S)
    charger.reboot(is_ahp=info.family == "AHP")
    ctx.worker.set_poll(live=False)
    ctx.worker.release()


def _password_set(charger: AlfenCharger, doc: dict[str, Any]) -> dict[str, Any]:
    """Change the installer password the CLI and this UI log in with."""
    password = _opt_text(doc, "password")
    if not password:
        raise ApiError(400, "name the new password")
    charger.set_password(password)
    return {
        "message": "Password changed. Update alfen.toml so the next login can use it."
    }


def _password_temporary(charger: AlfenCharger, doc: dict[str, Any]) -> dict[str, Any]:
    """Set a password the charger reverts from on its own."""
    password = _opt_text(doc, "password")
    hours = _opt_int(doc, "hours")
    if not password or hours is None:
        raise ApiError(400, "name the password and the hours")
    charger.set_temporary_password(password, hours)
    return {
        "message": f"Temporary password set; the charger reverts to the "
        f"previous one in {hours} hour(s)."
    }


def _password_recover(charger: AlfenCharger, doc: dict[str, Any]) -> dict[str, Any]:
    """Reset to the charger's default, with the code it shows on its screen."""
    code = _opt_text(doc, "code")
    if not code:
        raise ApiError(400, "name the recovery code from the charger")
    try:
        charger.reset_password(code)
    except httpx.HTTPStatusError as exc:
        raise ApiError(400, access.recovery_error(exc)) from None
    return {"message": "The password has been reset to the charger's default."}


def _password_pin(charger: AlfenCharger, doc: dict[str, Any]) -> dict[str, Any]:
    """Set, clear or disable the PIN the Eve Connect app asks a driver for.

    The three answers are different: a PIN sets one, an empty string lets the
    app in without one, and no key at all turns app access off.
    """
    pin = _opt_text(doc, "pin")
    if pin == "":
        charger.set_end_user_pin("")
        return {"message": "Eve Connect app access enabled without a PIN."}
    if pin is None:
        charger.disable_end_user_access()
        return {"message": "Eve Connect app access disabled."}
    if not access.PIN_RE.match(pin):
        raise ApiError(400, "the PIN must be 4 to 6 digits")
    charger.set_end_user_pin(pin)
    return {"message": "Eve Connect app access PIN set."}


_PASSWORD_ACTIONS: dict[
    str, Callable[[AlfenCharger, dict[str, Any]], dict[str, Any]]
] = {
    "set": _password_set,
    "temporary": _password_temporary,
    "recover": _password_recover,
    "pin": _password_pin,
}


def post_password(ctx: Context, req: Request) -> Response:
    """Set, time-limit or recover the login password, or the app PIN."""
    doc = req.json()
    action = str(doc.get("action") or "")
    run = _PASSWORD_ACTIONS.get(action)
    if run is None:
        raise ApiError(400, "action is set, temporary, recover or pin")

    def write(charger: AlfenCharger) -> dict[str, Any]:
        return run(charger, doc)

    return ok(ctx.worker.run(f"Changing the {action} password", write))


def post_secret(ctx: Context, req: Request) -> Response:
    """Install a write-only secret: its value in the body, or a file upload."""
    from alfenctl import secret
    from alfenctl.secret import SecretError

    name = req.param("name") or str(req.json().get("name") or "")
    try:
        item = secret.find(name)
    except SecretError as exc:
        raise ApiError(400, str(exc)) from None

    if req.body and not req.body.lstrip().startswith(b"{"):
        data = req.body
    else:
        value = _opt_text(req.json(), "value")
        if value is None:
            raise ApiError(400, "the secret's value or file is missing")
        data = value.encode("utf-8")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "that file is far larger than anything a charger takes")

    def install(charger: AlfenCharger) -> dict[str, Any]:
        secret.install(charger, item, data)
        return {
            "message": f"Installed {item.name}. The charger applies it on its "
            "next restart."
        }

    return ok(ctx.worker.run(f"Installing {item.name}", install))


def post_tilt(ctx: Context, req: Request) -> Response:
    """Calibrate the tilt sensor: store where the charger stands as upright."""
    from alfenctl import tilt
    from alfenctl.tilt import TiltError

    def calibrate(charger: AlfenCharger) -> dict[str, Any]:
        try:
            state = tilt.read(charger)
            tilt.calibrate(charger, state)
        except TiltError as exc:
            raise ApiError(400, str(exc)) from None
        return {"message": "Tilt sensor calibrated to the current position."}

    return ok(ctx.worker.run("Calibrating the tilt sensor", calibrate))


def post_console(ctx: Context, req: Request) -> Response:
    """Send one console command (the app's Command Window)."""
    command = _opt_text(req.json(), "command")
    if not command:
        raise ApiError(400, "name the console command to send")

    def send(charger: AlfenCharger) -> dict[str, Any]:
        charger.send_command(command)
        return {"message": f"Sent '{command}'."}

    return ok(ctx.worker.run(f"Sending '{command}'", send))


def post_diagnostic(ctx: Context, req: Request) -> Response:
    """Submit a firmware-specific diagnostic through the station worker."""
    doc = req.json()
    command = (_opt_text(doc, "command") or "").strip()
    if not command:
        raise ApiError(400, "name the diagnostic command to send")
    sequence_id = doc.get("sequenceId")
    if type(sequence_id) is not int or not 0 <= sequence_id <= DIAGNOSTIC_SEQUENCE_MAX:
        raise ApiError(400, "sequenceId must be a whole number from 0 to 255")
    parameters = doc.get("parameters", [])
    if not isinstance(parameters, list) or not all(
        isinstance(value, str) for value in parameters
    ):
        raise ApiError(400, "parameters must be an ordered list of strings")

    def send(charger: AlfenCharger) -> dict[str, Any]:
        charger.send_diagnostic_command(command, sequence_id, parameters)
        return {
            "message": f"Submitted diagnostic '{command}' (sequence {sequence_id}). "
            "Submission does not confirm completion."
        }

    return ok(ctx.worker.run(f"Submitting diagnostic '{command}'", send))


def get_diagnostic_result(ctx: Context, req: Request) -> Response:
    """Read the current diagnostic result once, preserving its JSON fields."""
    return ok(
        ctx.worker.run(
            "Reading the diagnostic result",
            lambda charger: charger.fetch_diagnostic_result(),
        )
    )


def post_erase(ctx: Context, req: Request) -> Response:
    """Erase the settings, the personal data, or the transaction database."""
    doc = req.json()
    target = str(doc.get("target") or "")
    if target not in ("settings", "personal-data", "transactions"):
        raise ApiError(400, "target is settings, personal-data or transactions")

    def erase(charger: AlfenCharger) -> dict[str, Any]:
        is_ahp = charger.basic_info().family == "AHP"
        if target == "settings":
            charger.clear_settings(is_ahp=is_ahp)
            message = "Settings erased; reboot the charger to start on defaults."
        elif target == "personal-data":
            charger.clear_personal_data()
            message = "Personal data erased."
        else:
            charger.erase_transactions(is_ahp=is_ahp)
            message = "Transaction database erased."
        return {"message": message}

    return ok(ctx.worker.run(f"Erasing {target}", erase))


# --- backup and restore ---------------------------------------------------------------------


def get_backup(ctx: Context, req: Request) -> Response:
    """Dump the charger's properties as a downloadable file.

    ``?format=json|xml|exml`` picks the shape (the app's own settings format
    for the last two); ``?writableOnly=1`` skips what a restore could not
    write back anyway.
    """
    from alfenctl import properties, settings
    from alfenctl.charger import ChargerInfo

    fmt = req.param("format", "json")
    if fmt not in ("json", "xml", "exml"):
        raise ApiError(400, "format is json, xml or exml")

    def read(charger: AlfenCharger) -> tuple[str, bytes, ChargerInfo]:
        props = properties.collect(charger, ctx.catalog, on_category=_walking(ctx))
        if req.flag("writableOnly"):
            props = [p for p in props if p.writable]
        info = charger.basic_info()
        if fmt == "json":
            payload = (
                json.dumps(
                    [{"id": p.id_str, "name": p.name, "value": p.value} for p in props],
                    indent=2,
                )
                + "\n"
            )
            content_type = "application/json"
        else:
            payload = settings.build(
                [(p.id_str, p.encoded(p.value)) for p in props],
                model=info.model or "",
                sockets=str(info.sockets or ""),
                identity=info.identity or info.object_id,
                host=charger.station.ip,
                port=str(charger.station.port),
            )
            if fmt == "exml":
                payload = settings.encrypt_exml(payload)
            content_type = "application/xml"
        return content_type, payload.encode("utf-8"), info

    content_type, payload, info = ctx.worker.run("Reading every property", read)
    suffix = {"json": ".json", "xml": ".xml", "exml": ".exml"}[fmt]
    filename = f"{info.object_id or 'charger'}{suffix}"
    return Response(
        body=payload,
        content_type=f"{content_type}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
        },
    )


def post_restore(ctx: Context, req: Request) -> Response:
    """Apply an uploaded property file: preview the diff, or write it.

    ``?apply=1`` writes what a dry run only shows; the diff is computed
    against the live charger either way, by the same
    :func:`alfenctl.properties.plan_import` that backs ``alfenctl import``,
    so the browser is told about the read-only and device-bound properties
    the terminal names rather than being handed a shorter list with no
    explanation for the difference.
    """
    from alfenctl import properties

    if not req.body:
        raise ApiError(400, "no file content was uploaded")
    try:
        entries = properties.parse_entries(req.body.decode("utf-8", "replace"))
    except ValueError as exc:
        raise ApiError(400, f"cannot read the file: {exc}") from None

    force = req.flag("force")
    applying = req.flag("apply")

    def run(charger: AlfenCharger) -> dict[str, Any]:
        plan = properties.plan_import(charger, ctx.catalog, entries, force=force)
        doc: dict[str, Any] = {
            "changes": [
                {
                    "id": c.prop.id_str,
                    "name": c.prop.name,
                    "title": c.prop.title,
                    "from": c.before,
                    "to": c.after,
                }
                for c in plan.changes
            ],
            "skippedBound": [{"id": p.id_str, "name": p.name} for p in plan.bound],
            "skippedReadOnly": [
                {"id": p.id_str, "name": p.name} for p in plan.read_only
            ],
            "invalid": [{"id": i, "error": why} for i, why in plan.invalid],
            "errors": plan.missing,
        }
        if not applying:
            return doc
        writes = plan.writes
        charger.write_properties(writes)
        doc["applied"] = len(writes)
        return doc

    label = "Applying the settings file" if applying else "Previewing the settings file"
    return ok(ctx.worker.run(label, run))


def post_preset(ctx: Context, req: Request) -> Response:
    """Apply one of Alfen's published presets, as a job."""
    from alfenctl import meter_map as meter_map_mod, settings as settings_mod
    from alfenctl.repo import fetch_preset, fetch_preset_bytes

    doc = req.json()
    wanted = str(doc.get("name") or "").strip()
    if not wanted:
        raise ApiError(400, "name the preset to apply")
    config = _repo_config(ctx)

    def run(charger: AlfenCharger, job: Job) -> None:
        job.report(0.0, f"Fetching preset {wanted}", force=True)
        presets = _match_presets(config, wanted.lower())
        if not presets:
            raise RuntimeError(f"no preset matches {wanted!r}")
        preset = presets[0]
        job.result = {"preset": schema.preset_json(preset)}
        if preset.is_backoffice:
            from alfenctl.ocpp import (
                BACKOFFICE_CLEARED,
                BACKOFFICE_NAME_MAX,
                P_BACKOFFICE_NAME,
            )
            from alfenctl.values import VISIBLE_STRING

            blob = fetch_preset_bytes(preset, config)
            live = {
                p.key: p
                for p in charger.fetch_properties_by_ids(list(BACKOFFICE_CLEARED))
            }
            cleared = {
                key: ("", prop.data_type) for key, prop in live.items() if prop.writable
            }
            if cleared:
                charger.write_properties(cleared)
            charger.upload_firmware(blob)
            name = preset.label[:BACKOFFICE_NAME_MAX]
            charger.write_properties({P_BACKOFFICE_NAME: (name, VISIBLE_STRING)})
            job.report(1.0, "Preset uploaded; reboot to apply it", force=True)
            job.result["note"] = "Reboot the charger to apply the preset."
            return
        text = fetch_preset(preset, config)
        if preset.is_meter_map:
            wanted_map = meter_map_mod.parse_json(text)
            current = meter_map_mod.read(charger)
            meter_map_mod.apply(
                charger,
                wanted_map,
                capacity=current.capacity or len(wanted_map.entries),
            )
            job.report(1.0, "Register map written", force=True)
            return

        job.report(0.2, "Writing the preset's properties", force=True)
        entries = settings_mod.parse(text).as_entries()
        _preset_entries(charger, ctx, entries, job)

    job = ctx.worker.start_job(f"Applying preset {wanted}", run)
    return ok({"job": job.as_dict()}, status=202)


def _preset_entries(
    charger: AlfenCharger, ctx: Context, entries: list[dict[str, Any]], job: Job
) -> None:
    """Write a preset's property entries, reporting progress per batch.

    ``force`` because a preset is not a charger's own settings file: it comes
    from the operator's own server and carries back-office addresses, not the
    serial and MAC that make :func:`plan_import` hold a settings file back.
    """
    from alfenctl import properties

    plan = properties.plan_import(charger, ctx.catalog, entries, force=True)
    writes = plan.writes
    if writes:
        charger.write_properties(writes)
    job.report(
        1.0,
        f"Wrote {len(writes)} propert{'y' if len(writes) == 1 else 'ies'}",
        force=True,
    )
    job.result = {"written": len(writes)}


# --- routing table -----------------------------------------------------------------------


ROUTES: dict[tuple[str, str], Route[Context]] = {
    ("GET", "/api/state"): Route(get_state),
    ("GET", "/api/stations"): Route(get_stations),
    ("GET", "/api/dashboard"): Route(get_dashboard),
    ("GET", "/api/status"): Route(get_status),
    ("GET", "/api/categories"): Route(get_categories),
    ("GET", "/api/properties"): Route(get_properties),
    ("GET", "/api/logs"): Route(get_logs),
    ("GET", "/api/jobs"): Route(get_jobs),
    ("GET", "/api/firmware/available"): Route(get_firmware_available),
    ("POST", "/api/station"): Route(post_station, write=True),
    ("POST", "/api/link"): Route(post_link),
    ("POST", "/api/live"): Route(post_live),
    ("POST", "/api/properties"): Route(post_properties, write=True),
    ("GET", "/api/lb"): Route(get_loadbalancing),
    ("POST", "/api/lb"): Route(post_loadbalancing, write=True),
    ("GET", "/api/auth"): Route(get_authorization),
    ("POST", "/api/auth"): Route(post_authorization, write=True),
    ("GET", "/api/ocpp"): Route(get_ocpp),
    ("POST", "/api/ocpp"): Route(post_ocpp, write=True),
    ("GET", "/api/tags"): Route(get_tags),
    ("POST", "/api/tags"): Route(post_tags, write=True),
    ("GET", "/api/master-tag"): Route(get_master_tag),
    ("POST", "/api/master-tag"): Route(post_master_tag, write=True),
    ("GET", "/api/connectivity"): Route(get_connectivity),
    ("GET", "/api/wifi/scan"): Route(get_wifi_scan),
    ("POST", "/api/wifi"): Route(post_wifi, write=True),
    ("GET", "/api/meter-test"): Route(get_meter_test),
    ("GET", "/api/meter-map"): Route(get_meter_map),
    ("POST", "/api/meter-map"): Route(post_meter_map, write=True, raw_body=True),
    ("GET", "/api/doctor"): Route(get_doctor),
    ("GET", "/api/profiles"): Route(get_profiles),
    ("POST", "/api/profiles"): Route(post_profiles, write=True),
    ("GET", "/api/direct-start"): Route(get_direct_start),
    ("POST", "/api/direct-start"): Route(post_direct_start, write=True),
    ("GET", "/api/scn"): Route(get_scn),
    ("POST", "/api/scn"): Route(post_scn, write=True),
    ("GET", "/api/transactions"): Route(get_transactions),
    ("GET", "/api/secrets"): Route(get_secrets),
    ("POST", "/api/secret"): Route(post_secret, write=True, raw_body=True),
    ("POST", "/api/password"): Route(post_password, write=True),
    ("POST", "/api/tilt"): Route(post_tilt, write=True),
    ("GET", "/api/console"): Route(get_console_commands),
    ("POST", "/api/console"): Route(post_console, write=True),
    ("POST", "/api/diag"): Route(post_diagnostic, write=True),
    ("GET", "/api/diag"): Route(get_diagnostic_result),
    ("POST", "/api/erase"): Route(post_erase, write=True),
    ("GET", "/api/backup"): Route(get_backup),
    ("POST", "/api/restore"): Route(post_restore, write=True, raw_body=True),
    ("GET", "/api/presets"): Route(get_presets),
    ("GET", "/api/preset"): Route(get_preset),
    ("POST", "/api/actions/reboot"): Route(post_reboot, write=True),
    ("POST", "/api/actions/time-sync"): Route(post_time_sync, write=True),
    ("POST", "/api/actions/license"): Route(post_license, write=True),
    ("POST", "/api/cloud"): Route(post_cloud),
    ("POST", "/api/cloud/login"): Route(post_cloud_login),
    ("POST", "/api/actions/controls"): Route(post_controls, write=True),
    ("POST", "/api/actions/firmware-release"): Route(post_firmware_release, write=True),
    ("POST", "/api/actions/logo"): Route(post_logo, write=True, raw_body=True),
    ("POST", "/api/actions/firmware"): Route(post_firmware, write=True, raw_body=True),
}
