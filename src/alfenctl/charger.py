"""What the charger's HTTP API offers: one method per endpoint.

The connection itself -- making it, logging in, keeping the session across
the charger's short idle timeout, and streaming a firmware image through it
without the firmware resetting the socket -- is
:class:`alfenctl.transport.ChargerTransport`, and none of it is repeated
here.  What is here is the fifty-odd things the API can be *asked*, grouped
by subject and each one a line or two over
:meth:`~alfenctl.transport.ChargerTransport.request`.

That split is the point: the transport has a handful of hard-won details in
it and is read when something is wrong with the connection; this file is
read when you want to know what the charger can do.  Keeping them in one
1200-line class meant every reading of either was a reading of both.

The endpoint names here, and their quirks, come from the Windows app's
``ICUNetwork.ICULanDevice`` -- the property pagination, the whitelist's verb
query, the two shapes of the erase command, the diagnostic pair.  Where the
app and the charger disagree, the comment says which was tested.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx

from alfenctl.errors import AlfenError
from alfenctl.firmware import FW_NO_ACTIVE_UPDATE, device_family, parse_fw_version
from alfenctl.transport import (
    ACCESS_READ_ONLY,
    DEFAULT_OLD_PASSWORD,
    DEFAULT_OLD_USER,
    HTTP_FORBIDDEN,
    HTTP_NOT_FOUND,
    HTTP_OK,
    HTTP_UNAUTHORIZED,
    IDS_QUERY_BATCH,
    MAX_PROP_PAGES,
    P_DEVICE_NAME,
    P_IDENTITY,
    P_MODEL,
    P_NR_SOCKETS,
    P_SERIAL,
    P_SW_VERSION,
    PROP_PAGE_SIZE,
    REBOOT_POLL_TIMEOUT_S,
    STORE_BATCH_SIZE,
    WHITELIST_CLEAR_TIMEOUT_S,
    WIFI_SCAN_TIMEOUT_S,
    ChargerInfo,
    ChargerTransport,
    LiveProperty,
    UploadError,
    _sockets_from_type,
    _timeout_kwargs,
    encode_property_value,
    parse_live_property,
    parse_prop_id,
)

# The vocabulary of an answer -- what a property looks like, what the charger
# says about itself, how a value is encoded to go back -- is parsed by the
# transport and handed out by the methods below, so it is asked for here by
# every module that calls one.  Re-exported rather than moved: the transport
# is where it is produced, and this is where it is used.
__all__ = [
    "ACCESS_READ_ONLY",
    "DEFAULT_OLD_PASSWORD",
    "DEFAULT_OLD_USER",
    "REBOOT_POLL_TIMEOUT_S",
    "AlfenCharger",
    "ChargerInfo",
    "LiveProperty",
    "UploadError",
    "encode_property_value",
    "parse_live_property",
    "parse_prop_id",
]


class AlfenCharger(ChargerTransport):
    """Client for the charger-local API, matching ``ICUNetwork.ICULanDevice``.

    Every method below is one endpoint: a line or two over
    :meth:`~alfenctl.transport.ChargerTransport.request`, a docstring saying
    which of the Windows app's calls it mirrors, and a comment wherever the
    charger disagrees with the app about what that call does.
    """

    # -- properties -- the object dictionary, read and written in batches -----------------
    def categories(self) -> list[str]:
        """Return the property category names from GET /api/categories."""
        r = self.request("GET", "categories")
        return [str(c).strip('" ') for c in r.json().get("categories", [])]

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
            r = self.request("GET", f"prop?{query}&offset={offset}")
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
            r = self.request("GET", f"prop?ids={ids}")
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
            self.request("POST", "prop", json=body)

    # -- identity -- who this station is, in one round trip -------------------------------
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

    # -- history -- the event log and the transaction database ----------------------------
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
        r = self.request("GET", f"log?{query}")
        return r.text

    def fetch_transactions(self, offset: int = 0xFFFFFFFF) -> str:
        """Return one page of the transaction database from GET /api/transactions.

        Mirrors ``ICUTransactions.Read``: ``offset`` is a record offset and
        paging runs backwards from ``0xFFFFFFFF`` ("the newest"), each page
        answered with the offset to ask for next.  The body is text, not
        JSON; :mod:`alfenctl.transactions` parses it.
        """
        r = self.request("GET", f"transactions?offset={offset}")
        return r.text

    def erase_transactions(self, is_ahp: bool = False) -> None:
        """Erase the transaction database (``EraseTransactionDatabase``).

        NG chargers take the ``txerase`` console command; AHP has a
        database-reset endpoint instead.
        """
        if is_ahp:
            self.request("POST", "db/reset?dbname=transactions", content=b"")
        else:
            self.send_command("txerase")

    # -- the RFID whitelist ---------------------------------------------------------------
    def fetch_whitelist(self, index: int = 0) -> str:
        """Return one page of the RFID whitelist from GET /api/whitelist.

        ``index`` is a position in a *sparse* list, so an empty page is not
        the end of it; :mod:`alfenctl.whitelist` does the walking.
        """
        r = self.request("GET", f"whitelist?index={index}")
        return r.text

    def whitelist_verb(self, query: str) -> None:
        """Send a whitelist action: ``add=<tag>``, ``remove=<tag>``, ``clear``, ...

        These are query strings on the same endpoint, not a body
        (``ICUWhiteList``).  ``clear`` walks the charger's flash, so it gets
        the app's longer timeout.
        """
        timeout = WHITELIST_CLEAR_TIMEOUT_S if query == "clear" else None
        self.request("GET", f"whitelist?{query}", timeout=timeout)

    def add_tag(self, record: Mapping[str, Any]) -> None:
        """Write one whole whitelist record (``POST /api/addtag``)."""
        self.request("POST", "addtag", json=dict(record))

    # -- charging profiles ----------------------------------------------------------------
    def fetch_charging_profile_ids(self) -> httpx.Response:
        """``GET /api/chargingprofiles?id_list`` -- also how support is probed.

        Mirrors ``ICUChargingProfiles.SupportsChargingProfiles``/
        ``GetAllChargingProfileIds``: the endpoint answers 404 (raised as
        :class:`httpx.HTTPStatusError`) on firmware that does not implement
        it at all.
        """
        return self.request("GET", "chargingprofiles?id_list")

    def fetch_charging_profile(self, profile_id: int) -> httpx.Response:
        """``GET /api/chargingprofiles?cpid=<id>`` -- one profile's schedule."""
        return self.request("GET", f"chargingprofiles?cpid={profile_id}")

    def clear_charging_profile(self, profile_id: int | str) -> None:
        """Remove one profile, or every profile with ``"all"`` (``Clear``/``ClearAll``).

        A POST with an empty body, like the app (``content=""`` is not
        ``null`` in ``ExecuteWebRequest``, which is what selects POST).
        """
        self.request("POST", f"chargingprofiles?clear={profile_id}", content=b"")

    def add_charging_profile(self, profile: Mapping[str, Any]) -> httpx.Response:
        """``POST /api/chargingprofiles?add=`` with one profile as the JSON body.

        ``profile`` is the whole ``{"connectorId": ..., "csChargingProfiles":
        {...}}`` document; :mod:`alfenctl.charging_profiles` builds it.
        """
        return self.request("POST", "chargingprofiles?add=", json=dict(profile))

    # -- the Wi-Fi radio ------------------------------------------------------------------
    def wifi_scan(self) -> str:
        """Return raw JSON from ``GET /api/wifiscan`` (nearby networks).

        Mirrors ``ICULanDevice.ExecutedWifiScan``: a plain GET (no query,
        no body), given the app's longer 11 s timeout -- a scan takes a
        moment on the charger's radio. :mod:`alfenctl.wifi` parses the
        result.
        """
        r = self.request("GET", "wifiscan", timeout=WIFI_SCAN_TIMEOUT_S)
        return r.text

    # -- firmware -------------------------------------------------------------------------
    def firmware_status(self, timeout: float | None = None) -> tuple[bool, int]:
        """Return ``(uploadInProgress, EFirmwareUpdateStatus)`` from GET /api/firmware.

        ``timeout`` overrides the client's per-request timeout, for polling
        a charger that is mid-reboot (see :data:`REBOOT_POLL_TIMEOUT_S`).
        """
        r = self.request("GET", "firmware", timeout=timeout)
        text = r.text.replace(",}", "}")  # the app tolerates this trailing-comma quirk
        doc = json.loads(text) if text.strip() else {}
        in_progress = str(doc.get("uploadInProgress", "false")).lower() == "true"
        status_obj = doc.get("OD_fileFirmwareUpdateStatus") or {}
        if isinstance(status_obj, dict):
            status = int(status_obj.get("value", FW_NO_ACTIVE_UPDATE))
        else:
            status = FW_NO_ACTIVE_UPDATE
        return in_progress, status

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
        status = self.stream_upload(body, boundary)
        if status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
            self.login()  # session dropped between login and upload; re-auth and retry once
            status = self.stream_upload(body, boundary)
        if status is not None and status != HTTP_OK:
            raise UploadError(f"charger rejected the firmware upload: HTTP {status}")

    def commit_firmware(self) -> None:
        """Make the freshly-uploaded firmware permanent (forcefirmwarepermanent)."""
        self.send_command("forcefirmwarepermanent")

    # -- diagnostics ----------------------------------------------------------------------
    def _diagnostic_request(
        self, method: str, command: str, **kwargs: Any
    ) -> httpx.Response:
        """Send a diagnostic request and describe an unavailable endpoint."""
        try:
            return self.request(method, command, **kwargs)
        except httpx.HTTPStatusError as exc:
            if (
                exc.response.status_code == HTTP_NOT_FOUND
                and exc.request.url.path == self._url("diagtool")
            ):
                raise AlfenError(
                    "the diagnostic interface is unavailable on this charger "
                    f"(HTTP 404 for {exc.request.url}); support depends on the firmware"
                ) from exc
            raise

    def send_diagnostic_command(
        self,
        command: str,
        sequence_id: int,
        parameters: Sequence[str] = (),
        timeout: float | None = None,
    ) -> None:
        """Submit a command to ``POST /api/diagtool`` (``SendDiagCommand``).

        The sequence ID and each numbered parameter are JSON strings, as in
        the Windows client. HTTP success acknowledges submission only; read
        ``fetch_diagnostic_result`` separately to inspect progress/output.
        """
        self._diagnostic_request(
            "POST",
            "diagtool",
            json={
                "command": command,
                "sequenceID": str(sequence_id),
                "parameters": [
                    {f"param{index}": value} for index, value in enumerate(parameters)
                ],
            },
            timeout=timeout,
        )

    def fetch_diagnostic_result(self, timeout: float | None = None) -> Any:
        """Return the original JSON from ``GET /api/diagtool?result``.

        The Windows client reads version and DiagnosticResult's command,
        sequenceid, finished and result fields. Preserve their spelling and
        values, including string booleans and firmware-specific extra fields.
        This neither starts a diagnostic nor waits for it to finish.
        """
        response = self._diagnostic_request("GET", "diagtool?result", timeout=timeout)
        try:
            return response.json()
        except ValueError as exc:
            raise AlfenError("charger returned invalid diagnostic-result JSON") from exc

    # -- maintenance -- the three things that take a station out of service ---------------
    def reboot(self, is_ahp: bool = False) -> None:
        """Ask the charger to restart (``ICULanDevice.SendReboot``).

        NG chargers take the ``reboot`` console command; AHP has a reset
        endpoint, where ``type=hard`` is the equivalent of a power cycle
        (``type=soft`` restarts only the application).
        """
        if is_ahp:
            self.request("POST", "reset?type=hard", content=b"")
        else:
            self.send_command("reboot")

    def clear_settings(self, is_ahp: bool = False) -> None:
        """Erase the stored configuration (``ICULanDevice.ClearSettings``).

        The charger comes back up on its factory defaults.
        """
        if is_ahp:
            self.request("POST", "db/reset?dbname=configuration_item", content=b"")
        else:
            self.send_command("eepromx erase config")

    def clear_personal_data(self) -> None:
        """Erase personal data (``ClearPersonalData``): tags, transactions, logs."""
        self.request("POST", "clearpersonaldata", content=b"")

    # -- access -- the passwords and PINs, none of which read back ------------------------
    def set_password(self, new_password: str) -> None:
        """Set a new unique login password (the app's ``ChangePassword``).

        Used when an upgrade crosses the 5.0 firmware boundary, after which the
        charger requires a unique per-charger password instead of the shared
        default. Mirrors the app: ``POST /api/password`` with the new password,
        while logged in.
        """
        self.request("POST", "password", json={"password": new_password})

    def set_end_user_pin(self, pin: str) -> None:
        """Set (or, with ``pin=""``, enable without one) the Eve Connect app PIN.

        Mirrors ``ICULanDevice.SetEndUserPin``: the same ``POST
        /api/password`` endpoint as the admin login password, but with
        ``username: "end user"`` -- a second, independent credential the
        app's *Eve Connect app access* dialog manages (``DlgEndUserPin``).
        An empty pin enables access without requiring one.
        """
        self.request("POST", "password", json={"username": "end user", "password": pin})

    def disable_end_user_access(self) -> None:
        """Disable the Eve Connect app PIN entirely (``DisableEndUserAccess``)."""
        self.request("POST", "password", json={"username": "end user", "reset": True})

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
        self.request(
            "POST",
            "temporarypassword",
            json={"password": new_password, "expiration": hours},
        )

    # -- the clock ------------------------------------------------------------------------
    def send_clock(self, stamp: str, *, is_ahp: bool = False) -> None:
        """Tell the firmware the time, as ``ICULanDevice.SendDatetime`` does.

        Writing ``sysDateTime`` is not enough on its own: the firmware has to
        be told separately, and takes it two different ways -- NG chargers as
        the ``date`` console command, AHP as ``POST /api/datetime`` -- both
        carrying ``yyyy-MM-dd HH:mm:ss`` in UTC.

        Which moment to send, and how far ahead to aim it so that it is right
        when it lands, is :func:`alfenctl.clock.set`'s business, not this
        one's.  Everything here is the wire.
        """
        if is_ahp:
            self.request(
                "POST",
                "datetime",
                content=f'"{stamp}"'.encode(),
                headers={"Content-Type": "application/json"},
            )
        else:
            self.request("POST", "cmd", json={"command": f"date {stamp}"})

    # -- write-only domain items -- keys and certificates ---------------------------------
    def set_domain_item(self, item_type: int, data: bytes) -> None:
        """Install one write-only key or certificate (``ICUDomain.AddOrUpdateItem``).

        ``POST /api/domain`` with ``{"cmd":"add","type":<n>,"data":"<hex>"}``,
        where the hex is the value's bytes, uppercase and unseparated.  This
        is the only way in: the properties behind these items are ``wo`` in
        the EDS and ``POST /api/prop`` will not write them.  See
        :mod:`alfenctl.secret` for the item types.
        """
        body = {"cmd": "add", "type": int(item_type), "data": data.hex().upper()}
        self.request("POST", "domain", json=body)
