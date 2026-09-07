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
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

import httpx

from alfenctl import (
    __version__,
    clock,
    controls,
    hardware,
    loadbalancing,
    logs,
    setup,
    properties,
    status as status_mod,
)
from alfenctl.charger import AlfenCharger
from alfenctl.errors import AlfenError
from alfenctl.upgrade import install, send_image
from alfenctl.web import schema
from alfenctl.web.progress import DOWNLOAD_SHARE_OF_JOB, JobReporter
from alfenctl.web.session import Job, StationWorker, Target

# The largest upload we will take from the browser.  A firmware image is
# ~2 MB and a logo package well under 1 MB; anything at this size is a
# mistake, and we would rather say so than buffer it.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024

# How many log lines the log view asks for.
LOG_PAGE_LINES = 200

# What firmware without /api/chargingprofiles answers with.
HTTP_NOT_FOUND = 404


class ApiError(AlfenError):
    """A request that cannot be served, with the status to answer."""

    def __init__(self, status: int, message: str) -> None:
        """Record the HTTP status alongside the message."""
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Request:
    """One parsed HTTP request."""

    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def json(self) -> dict[str, Any]:
        """Parse the body as a JSON object."""
        if not self.body:
            return {}
        try:
            doc = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, f"malformed JSON body: {exc}") from None
        if not isinstance(doc, dict):
            raise ApiError(400, "expected a JSON object")
        return doc

    def param(self, name: str, default: str = "") -> str:
        """One query-string parameter."""
        return self.query.get(name, default)

    def flag(self, name: str, default: bool = False) -> bool:
        """One query-string parameter read as a boolean."""
        raw = self.query.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Response:
    """One reply, ready to write."""

    status: int = 200
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)


def ok(payload: Any, status: int = 200) -> Response:
    """Render a JSON reply."""
    return Response(status=status, body=json.dumps(payload).encode("utf-8"))


@dataclass
class Context:
    """Everything a handler needs besides the request."""

    worker: StationWorker
    read_only: bool = False
    debug: bool = False
    discover_time: float = 2.0
    config: Any = None
    sockets: int = 1  # how many sockets the last read reported
    follow_logs: bool = False
    log_last_id: int | None = None
    _catalog: Any = None

    @property
    def catalog(self) -> Any:
        """The EDS catalog, parsed once and reused."""
        if self._catalog is None:
            from alfenctl.eds import load_catalog

            self._catalog = load_catalog()
        return self._catalog


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
            "followLogs": ctx.follow_logs,
            "hasTarget": ctx.worker.target is not None,
        }
    )


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
    snapshot = schema.status_json(status_mod.collect(charger, ctx.sockets or 1))
    snapshot["at"] = time.time()
    return snapshot


def get_dashboard(ctx: Context, req: Request) -> Response:
    """One connection's worth of everything the dashboard shows."""

    def read(charger: AlfenCharger) -> dict[str, Any]:
        info = charger.basic_info()
        ctx.sockets = info.sockets or 1
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
    ctx.log_last_id = newest if newest is not None else ctx.log_last_id
    return ok({"lines": [schema.log_json(line) for line in page]})


def get_clients(ctx: Context, req: Request) -> Response:
    """Who is watching: one row per open event stream.

    The link pill counts them; this says which they are, which is what tells
    "my other tab" from "someone else on the network holding the charger".
    """
    return ok({"clients": [schema.client_json(c) for c in ctx.worker.events.clients()]})


def post_focus(ctx: Context, req: Request) -> Response:
    """Ask every open tab to bring the page it already has to the front.

    This is how a second ``alfenctl ui`` avoids opening a second tab: it
    finds the port taken, asks whoever holds it to raise the page, and stops.
    Nothing on the charger changes, so a read-only server answers it too --
    and the reply names the app, which is how the caller knows it reached
    another alfenctl rather than something else listening on that port.
    """
    ctx.worker.events.publish("focus", {"at": time.time()})
    clients = ctx.worker.events.clients()
    return ok(
        {
            "app": "alfenctl",
            "version": __version__,
            "clients": ctx.worker.events.subscriber_count,
            # The caller is a second `alfenctl ui` with no stream of its own,
            # so it can only name the tabs it just raised if we name them.
            "watching": schema.name_watchers(clients),
        }
    )


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
    ctx.sockets = 1
    ctx.log_last_id = None
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
        ctx.follow_logs = bool(doc["logs"])
    ctx.worker.set_poll(
        live=bool(doc["enabled"]) if "enabled" in doc else None,
        interval=float(doc["interval"]) if doc.get("interval") else None,
    )
    return ok({"link": ctx.worker.link_state(), "followLogs": ctx.follow_logs})


def make_poll(ctx: Context) -> Callable[[AlfenCharger], None]:
    """Build the function the worker runs on every live refresh."""

    def poll(charger: AlfenCharger) -> None:
        snapshot = _read_status(ctx, charger)
        ctx.worker.events.publish("status", snapshot, sticky=True)
        if ctx.follow_logs:
            tail = logs.poll(charger, ctx.log_last_id)
            ctx.log_last_id = tail.last_id
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
    at once is one hold of the connection rather than two.
    """
    doc = req.json()
    sockets: dict[int, float] = {}
    for item in doc.get("sockets") or []:
        if not isinstance(item, dict) or "number" not in item:
            raise ApiError(400, "each socket needs a 'number' and a current")
        amps = _amps(item, "maxCurrentA")
        if amps is not None:
            sockets[int(item["number"])] = amps
    intensity = doc.get("intensity")
    auto_dim = doc.get("autoDim")

    def write(charger: AlfenCharger) -> dict[str, Any]:
        try:
            after = controls.apply(
                charger,
                station_max_a=_amps(doc, "stationMaxCurrentA"),
                sockets=sockets,
                intensity=None if intensity is None else int(intensity),
                auto_dim=None if auto_dim is None else bool(auto_dim),
                temp_alarm_low=_number(doc, "temperatureAlarmLowC", "degrees"),
                temp_alarm_high=_number(doc, "temperatureAlarmHighC", "degrees"),
            )
        except controls.ControlError as exc:
            raise ApiError(400, str(exc)) from None
        return schema.controls_json(after) or {}

    result = ctx.worker.run("Writing charger settings", write)
    return ok({"controls": result})


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


def _discard(path: Path) -> None:
    """Remove a spooled upload and the directory it was written into."""
    import shutil

    shutil.rmtree(path.parent, ignore_errors=True)


def _spool(req: Request, suffix: str) -> Path:
    """Write an uploaded body to a temporary file for the modules that want a path."""
    if not req.body:
        raise ApiError(400, "no file content was uploaded")
    if len(req.body) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "that file is far larger than anything a charger takes")
    name = Path(req.param("filename", "upload")).name or "upload"
    directory = Path(tempfile.mkdtemp(prefix="alfenctl-ui-"))
    path = directory / (name if Path(name).suffix else name + suffix)
    path.write_bytes(req.body)
    return path


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
            _discard(path)
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
                report=JobReporter(job, start=0.1),
                label="Uploading the logo",
                is_ahp=kind == "tvf",
            )
        finally:
            _discard(path)
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

        def on_bytes(done: int, total: int | None) -> None:
            share = (done / total) if total else 0.0
            job.report(DOWNLOAD_SHARE_OF_JOB * share)

        job.report(message=f"Downloading {match.name}", force=True)
        family = (ctx.worker.info.family if ctx.worker.info else "") or ""
        try:
            path = download(
                match, family, config=config, cache_dir=cache_dir, on_progress=on_bytes
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
            _discard(path)
    info = charger.basic_info()
    result = check_compatibility(info.family, info.firmware_version, image)
    job.result = {
        "notes": list(result.notes),
        "warnings": list(result.warnings),
        "errors": list(result.errors),
    }
    if not result.ok and not force:
        raise ApiError(400, "; ".join(result.errors) or "incompatible firmware")

    report = JobReporter(job, start=job.progress or 0.0)
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


def get_network(ctx: Context, req: Request) -> Response:
    """Where the charger is on the network, per interface."""
    from alfenctl import network

    state = ctx.worker.run("Reading the network", lambda charger: network.read(charger))
    return ok({"network": schema.network_json(state)})


def get_wifi_scan(ctx: Context, req: Request) -> Response:
    """Scan with the charger's own radio, switching it on first if asked.

    The radio takes seconds to come up, so enabling is done under the same
    worker task as the scan and the reply says which happened.
    """
    from alfenctl import network, wifi

    def scan(charger: AlfenCharger) -> dict[str, Any]:
        state = network.read(charger)
        enabled = False
        obstacle = state.scan_obstacle()
        if obstacle and req.flag("enable") and state.wifi_hardware is not False:
            network.enable(charger)
            state = network.wait_for_radio(charger)
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


def _scn_probe_peers(ctx: Context, charger: AlfenCharger) -> list[Any]:
    """Probe the LAN for the other chargers in this charger's network.

    The CLI opens one connection per peer; the worker owns ours, so this
    reaches around it the same way ``alfenctl scn --peers`` does.
    """
    import argparse

    from alfenctl.cli.commands.scn import _scn_probe_peers as cli_probe

    args = argparse.Namespace(discover_time=ctx.discover_time)
    found = cli_probe(args, charger.station.ip, charger.username, charger.password)
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
    from alfenctl import meter_map as meter_map_mod
    from alfenctl import settings as settings_mod
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

    The note goes with it.  Two thirds of this table has no command in it,
    which reads as a table two thirds broken until somebody says why the
    column is empty -- the terminal prints that sentence under
    ``alfenctl cmd --list``, and it is the same sentence about the same
    table, so it travels with the table rather than being written out a
    second time in another language.
    """
    from alfenctl.cli.commands.maintenance import (
        CONSOLE_COMMANDS,
        CONSOLE_UNKNOWN_NOTE,
    )

    return ok(
        {
            "commands": [schema.console_command_json(*row) for row in CONSOLE_COMMANDS],
            "note": CONSOLE_UNKNOWN_NOTE,
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
    """Write the load-balancing and solar settings that were named."""
    from alfenctl import loadbalancing
    from alfenctl.loadbalancing import LoadBalancingError

    doc = req.json()
    flags = _flags(doc, "static", "active", "phaseSwitching", "measurementIncludesEv")
    boost = doc.get("solarBoost")
    if boost is not None and not isinstance(boost, dict):
        raise ApiError(400, "solarBoost must map a socket number to true or false")

    def write(charger: AlfenCharger) -> dict[str, Any]:
        try:
            after = loadbalancing.apply(
                charger,
                static=flags.get("static"),
                active=flags.get("active"),
                protocol=_opt_int(doc, "protocol"),
                data_source=_opt_int(doc, "dataSource"),
                max_meter_current_a=_number(doc, "maxMeterCurrentA", "amps"),
                safe_current_a=_number(doc, "safeCurrentA", "amps"),
                max_imbalance_a=_number(doc, "maxImbalanceA", "amps"),
                phase_rotation=_opt_text(doc, "phaseRotation"),
                measurement_includes_ev=flags.get("measurementIncludesEv"),
                phase_switching=flags.get("phaseSwitching"),
                max_allowed_phases=_opt_int(doc, "maxAllowedPhases"),
                solar_mode=_opt_int(doc, "solarMode"),
                solar_green_share=_opt_int(doc, "solarGreenShare"),
                solar_comfort_w=_opt_int(doc, "solarComfortW"),
                solar_boost=(
                    {int(k): bool(v) for k, v in boost.items()} if boost else None
                ),
            )
        except LoadBalancingError as exc:
            raise ApiError(400, str(exc)) from None
        return schema.loadbalancing_json(after) or {}

    return ok({"loadbalancing": ctx.worker.run("Writing load balancing", write)})


def post_authorization(ctx: Context, req: Request) -> Response:
    """Write the authorization settings that were named."""
    from alfenctl import authorization
    from alfenctl.authorization import AuthorizationError

    doc = req.json()
    flags = _flags(
        doc,
        "whitelist",
        "localList",
        "restartAfterOutage",
        "remoteTxRequests",
        "stopOnInvalidTag",
        "abortConcurrent",
    )

    def write(charger: AlfenCharger) -> dict[str, Any]:
        try:
            after = authorization.apply(
                charger,
                mode=_opt_int(doc, "mode"),
                plug_and_charge_id=_opt_text(doc, "plugAndChargeId"),
                whitelist=flags.get("whitelist"),
                local_list=flags.get("localList"),
                restart_after_outage=flags.get("restartAfterOutage"),
                max_outage_s=_opt_int(doc, "maxOutageS"),
                remote_tx_requests=flags.get("remoteTxRequests"),
                stop_on_invalid_tag=flags.get("stopOnInvalidTag"),
                abort_concurrent=flags.get("abortConcurrent"),
                connection_timeout_s=_opt_int(doc, "connectionTimeoutS"),
                authorization_timeout_s=_opt_int(doc, "authorizationTimeoutS"),
                online_action=_opt_int(doc, "onlineAction"),
                offline_action=_opt_int(doc, "offlineAction"),
            )
        except AuthorizationError as exc:
            raise ApiError(400, str(exc)) from None
        return schema.authorization_json(after) or {}

    return ok({"authorization": ctx.worker.run("Writing authorization", write)})


def post_ocpp(ctx: Context, req: Request) -> Response:
    """Write the backoffice connection settings that were named."""
    from alfenctl import ocpp
    from alfenctl.ocpp import OcppError

    doc = req.json()
    flags = _flags(doc, "sendStationStatus", "infoNotifications", "proxyEnabled")

    def write(charger: AlfenCharger) -> dict[str, Any]:
        try:
            after = ocpp.apply(
                charger,
                connect_method=_opt_int(doc, "connectMethod"),
                protocol=_opt_text(doc, "protocol"),
                wired_url=_opt_text(doc, "wiredUrl"),
                wired_path=_opt_text(doc, "wiredPath"),
                mobile_url=_opt_text(doc, "mobileUrl"),
                mobile_path=_opt_text(doc, "mobilePath"),
                heartbeat_s=_opt_int(doc, "heartbeatS"),
                ping_pong_s=_opt_int(doc, "pingPongS"),
                meter_interval_s=_opt_int(doc, "meterIntervalS"),
                aligned_interval_s=_opt_int(doc, "alignedIntervalS"),
                send_station_status=flags.get("sendStationStatus"),
                status_mode=_opt_int(doc, "statusMode"),
                info_notifications=flags.get("infoNotifications"),
                tx_attempts=_opt_int(doc, "txAttempts"),
                tx_retry_s=_opt_int(doc, "txRetryS"),
                cpo_name=_opt_text(doc, "cpoName"),
                security_profile=_opt_int(doc, "securityProfile"),
                proxy_enabled=flags.get("proxyEnabled"),
                proxy_address=_opt_text(doc, "proxyAddress"),
                proxy_user=_opt_text(doc, "proxyUser"),
            )
        except OcppError as exc:
            raise ApiError(400, str(exc)) from None
        return schema.ocpp_json(after) or {}

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
    from alfenctl import network
    from alfenctl.network import NetworkError

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
                after = network.connect(charger, ssid, psk, security=security)
            elif action == "enable":
                after = network.enable(charger)
            elif action == "disconnect":
                after = network.disconnect(charger)
            elif action == "ap":
                enabled = doc.get("enabled")
                after = network.set_access_point(
                    charger,
                    enabled=None if enabled is None else bool(enabled),
                    start=None,
                )
            else:
                raise ApiError(400, "action is connect, enable, disconnect or ap")
        except NetworkError as exc:
            raise ApiError(400, str(exc)) from None
        return schema.network_json(after) or {}

    label = {"connect": f"Joining {ssid}", "ap": "Switching the access point"}.get(
        action, f"Wi-Fi {action}"
    )
    return ok({"network": ctx.worker.run(label, write)})


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


def post_password(ctx: Context, req: Request) -> Response:
    """Set, time-limit or recover the login password, or the app PIN."""
    doc = req.json()
    action = str(doc.get("action") or "")

    def write(charger: AlfenCharger) -> dict[str, Any]:
        if action == "set":
            password = _opt_text(doc, "password")
            if not password:
                raise ApiError(400, "name the new password")
            charger.set_password(password)
            return {
                "message": "Password changed. Update alfen.toml so the next "
                "login can use it."
            }
        if action == "temporary":
            password = _opt_text(doc, "password")
            hours = _opt_int(doc, "hours")
            if not password or hours is None:
                raise ApiError(400, "name the password and the hours")
            charger.set_temporary_password(password, hours)
            return {
                "message": f"Temporary password set; the charger reverts to the "
                f"previous one in {hours} hour(s)."
            }
        if action == "recover":
            code = _opt_text(doc, "code")
            if not code:
                raise ApiError(400, "name the recovery code from the charger")
            try:
                charger.reset_password(code)
            except httpx.HTTPStatusError as exc:
                raise ApiError(400, _recovery_error(exc)) from None
            return {"message": "The password has been reset to the charger's default."}
        if action == "pin":
            pin = _opt_text(doc, "pin")
            if pin == "":
                charger.set_end_user_pin("")
                return {"message": "Eve Connect app access enabled without a PIN."}
            if pin is None:
                charger.disable_end_user_access()
                return {"message": "Eve Connect app access disabled."}
            if not _PIN_RE.match(pin):
                raise ApiError(400, "the PIN must be 4 to 6 digits")
            charger.set_end_user_pin(pin)
            return {"message": "Eve Connect app access PIN set."}
        raise ApiError(400, "action is set, temporary, recover or pin")

    return ok(ctx.worker.run(f"Changing the {action} password", write))


_PIN_RE = __import__("re").compile(r"^[0-9]{4,6}$")


def _recovery_error(exc: httpx.HTTPStatusError) -> str:
    """Turn the charger's refusal of a reset code into the app's wording."""
    from alfenctl.cli.commands.access import _recovery_error as cli_wording

    return cli_wording(exc)


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
    import json as _json

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
                _json.dumps(
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
    against the live charger either way, exactly as ``alfenctl import``
    previews it.
    """
    import json as _json

    from alfenctl import properties, settings
    from alfenctl.values import coerce_input, is_portable, values_equal

    if not req.body:
        raise ApiError(400, "no file content was uploaded")
    text = req.body.decode("utf-8", "replace")
    try:
        if text.lstrip().startswith("<") or settings.looks_encrypted(text):
            entries = list(settings.parse(text).as_entries())
        else:
            data = _json.loads(text)
            if not isinstance(data, list) or not all(
                isinstance(e, dict) and "id" in e and "value" in e for e in data
            ):
                raise ValueError('expected a JSON array of {"id", "value"} entries')
            entries = data
    except (ValueError, _json.JSONDecodeError) as exc:
        raise ApiError(400, f"cannot read the file: {exc}") from None

    force = req.flag("force")
    applying = req.flag("apply")

    def run(charger: AlfenCharger) -> dict[str, Any]:
        queries = [str(e["id"]) for e in entries]
        props, errors = properties.resolve(charger, ctx.catalog, queries)
        by_id = {p.id_str: p for p in props}
        writes: dict[tuple[int, int], tuple[Any, int | None]] = {}
        plan: list[dict[str, Any]] = []
        skipped_bound = 0
        for entry in entries:
            prop = by_id.get(str(entry["id"]))
            if prop is None or not prop.writable:
                continue
            try:
                value = coerce_input(prop, entry["value"])
            except ValueError:
                continue
            if not is_portable(prop.key) and not force:
                if not values_equal(prop, value):
                    skipped_bound += 1
                continue
            if values_equal(prop, value):
                continue
            writes[prop.key] = (value, prop.data_type)
            plan.append(
                {
                    "id": prop.id_str,
                    "name": prop.name,
                    "title": prop.title,
                    "from": prop.encoded(prop.value),
                    "to": prop.encoded(value),
                }
            )
        if not applying:
            return {
                "changes": plan,
                "skippedBound": skipped_bound,
                "errors": errors,
            }
        charger.write_properties(writes)
        return {
            "applied": len(writes),
            "changes": plan,
            "skippedBound": skipped_bound,
            "errors": errors,
        }

    label = "Applying the settings file" if applying else "Previewing the settings file"
    return ok(ctx.worker.run(label, run))


def post_preset(ctx: Context, req: Request) -> Response:
    """Apply one of Alfen's published presets, as a job."""
    from alfenctl import meter_map as meter_map_mod
    from alfenctl import settings as settings_mod
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
            from alfenctl.cli.commands.props import (
                BACKOFFICE_CLEARED,
                P_BACKOFFICE_NAME,
                BACKOFFICE_NAME_MAX,
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
    """Write a preset's property entries, reporting progress per batch."""
    from alfenctl import properties as properties_mod
    from alfenctl.values import coerce_input, values_equal

    queries = [str(e["id"]) for e in entries]
    props, _errors = properties_mod.resolve(charger, ctx.catalog, queries)
    by_id = {p.id_str: p for p in props}
    writes: dict[tuple[int, int], tuple[Any, int | None]] = {}
    for entry in entries:
        prop = by_id.get(str(entry["id"]))
        if prop is None or not prop.writable:
            continue
        try:
            value = coerce_input(prop, entry["value"])
        except ValueError:
            continue
        if values_equal(prop, value):
            continue
        writes[prop.key] = (value, prop.data_type)
    if writes:
        charger.write_properties(writes)
    job.report(
        1.0,
        f"Wrote {len(writes)} propert{'y' if len(writes) == 1 else 'ies'}",
        force=True,
    )
    job.result = {"written": len(writes)}


# --- routing table -----------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    """One endpoint: what runs it, and whether it changes anything."""

    handler: Callable[[Context, Request], Response]
    write: bool = False
    raw_body: bool = False  # takes an uploaded file rather than JSON


ROUTES: dict[tuple[str, str], Route] = {
    ("GET", "/api/state"): Route(get_state),
    ("GET", "/api/stations"): Route(get_stations),
    ("GET", "/api/dashboard"): Route(get_dashboard),
    ("GET", "/api/status"): Route(get_status),
    ("GET", "/api/categories"): Route(get_categories),
    ("GET", "/api/properties"): Route(get_properties),
    ("GET", "/api/logs"): Route(get_logs),
    ("GET", "/api/jobs"): Route(get_jobs),
    ("GET", "/api/clients"): Route(get_clients),
    ("POST", "/api/focus"): Route(post_focus),
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
    ("GET", "/api/network"): Route(get_network),
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
    ("POST", "/api/erase"): Route(post_erase, write=True),
    ("GET", "/api/backup"): Route(get_backup),
    ("POST", "/api/restore"): Route(post_restore, write=True, raw_body=True),
    ("GET", "/api/presets"): Route(get_presets),
    ("GET", "/api/preset"): Route(get_preset),
    ("POST", "/api/actions/reboot"): Route(post_reboot, write=True),
    ("POST", "/api/actions/time-sync"): Route(post_time_sync, write=True),
    ("POST", "/api/actions/license"): Route(post_license, write=True),
    ("POST", "/api/actions/controls"): Route(post_controls, write=True),
    ("POST", "/api/actions/firmware-release"): Route(post_firmware_release, write=True),
    ("POST", "/api/actions/logo"): Route(post_logo, write=True, raw_body=True),
    ("POST", "/api/actions/firmware"): Route(post_firmware, write=True, raw_body=True),
}


def parse_query(raw: str) -> dict[str, str]:
    """Flatten a query string to the last value of each parameter."""
    return {k: v[-1] for k, v in parse_qs(raw, keep_blank_values=True).items()}
