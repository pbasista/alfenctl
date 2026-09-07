"""Shared fixtures and helpers for the test suite.

The bulk of it is :class:`FakeCharger`, which stands in for a charger in
the CLI and web tests: it answers the calls the commands make, out of
documents the test can edit, and records what was written to it.  Nothing
here reaches the network.
"""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Callable
from datetime import datetime, timezone

import httpx
import pytest

from alfenctl.charger import AlfenCharger, ChargerInfo
from alfenctl.discovery import Station

HEADER_LEN = 160  # the Alfen firmware container header is always 160 bytes


def make_fwi(*, magic: int = 0xA1FE0021, corrupt: bool = False) -> bytes:
    """Build a synthetic Alfen firmware container with a valid (or corrupted) header CRC."""
    header = bytearray(HEADER_LEN)
    struct.pack_into("<I", header, 4, HEADER_LEN)  # header-length field
    struct.pack_into("<I", header, 8, magic)  # magic (0xA1FE00 | variant byte)
    for i in range(12, HEADER_LEN):  # deterministic filler for the CRC to cover
        header[i] = (i * 7) & 0xFF
    crc = zlib.crc32(bytes(header[4:HEADER_LEN])) & 0xFFFFFFFF
    struct.pack_into("<I", header, 0, crc)
    data = bytes(header) + b"payload"
    if corrupt:  # flip one header byte so the stored CRC no longer matches
        data = bytes(data[:100]) + bytes([data[100] ^ 0xFF]) + data[101:]
    return data


@pytest.fixture
def make_charger() -> Callable[..., AlfenCharger]:
    """Return a factory building an :class:`AlfenCharger` wired to a MockTransport handler."""

    def _make(
        handler: Callable[[httpx.Request], httpx.Response], *, https: bool = True
    ):
        station = Station(ip="10.0.0.1", port=443 if https else 80, https=https)
        return AlfenCharger(
            station, "admin", "secret", transport=httpx.MockTransport(handler)
        )

    return _make


STATION = Station(ip="192.168.11.42", port=443, hostname="alfen-ace0781464.local.")
INFO = ChargerInfo(
    object_id="ACE0781464",
    identity="ACE0781464",
    model="NG910-60027",
    family="NG",
    firmware="7.4.5-4415",
    firmware_version=(7, 4, 5),
    sockets=1,
)

# A small catalog-independent live reply used by the props/get/set flows.
LIVE_DOCS = {
    "/api/categories": {"categories": ["generic"]},
    "/api/prop": {
        "version": 2,
        "total": 3,
        "properties": [
            {
                "id": "2050_0",
                "access": 2,
                "type": 9,
                "len": 21,
                "cat": "generic",
                "value": "NG910-60027",
            },
            {
                "id": "2062_0",
                "access": 2,
                "type": 8,
                "len": 0,
                "cat": "generic",
                "value": 25.0,
            },
            # The display descriptor, as a real NG910-60027 reports it: a
            # 320x165 screen.  Without it a charger has no display at all,
            # which is what `logo.read_display` is for.
            {
                "id": "3260_1",
                "access": 1,
                "type": 6,
                "len": 0,
                "cat": "generic",
                "value": 320,
            },
            {
                "id": "3260_3",
                "access": 1,
                "type": 6,
                "len": 0,
                "cat": "generic",
                "value": 320,
            },
            {
                "id": "3260_4",
                "access": 1,
                "type": 6,
                "len": 0,
                "cat": "generic",
                "value": 165,
            },
            {
                "id": "100A_0",
                "access": 1,
                "type": 9,
                "len": 33,
                "cat": "generic",
                "value": "7.4.5-4415",
            },
        ],
    },
    "/api/status-props": [
        {"id": "2501_1", "value": 2},
        {"id": "2501_4", "value": 160},
        {"id": "2201_0", "value": 42.625},
    ],
    "/api/whitelist": [
        {"tag": "04A1B2C3", "parent": "", "status": 1, "expiryDate": "0"},
        {"tag": "04FFEE11", "parent": "", "status": 2, "expiryDate": "0"},
    ],
    "/api/transactions": [
        "1024_tx: id = 0000A1B2, socket1, "
        "2026-08-29 08:00:00 1200.500kWh 04A1B2C3D4E5 Y, "
        "2026-08-29 11:30:00 1215.750kWh 04A1B2C3D4E5 3 Y",
        "2048_mv: socket 1, 2026-08-29 09:00:00 1205.000kWh regular Y",
        "3072_tx: id = 0000C3D4, socket2, "
        "2026-08-30 08:00:00 900.000kWh 04FFEE1122 Y, "
        "2026-08-30 09:00:00 907.000kWh 04FFEE1122 1 Y",
    ],
    "/api/log": [
        "4294_2026-08-29T12:41:52.123Z:INFO:fw_update.c:212:Firmware upload started",
        "4295_2026-08-29T12:41:54.001Z:ERROR:fw_update.c:388:Rejecting upload: feature not licensed",
    ],
}


class FakeCharger:
    """Stands in for AlfenCharger in main(); implements what commands touch."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    log_page_lines = 2  # how many log lines one /api/log page holds
    erased = False
    station = STATION
    recovery_error = None
    end_user_pin: str | None = "unset"
    debug = False
    upload_in_progress = False

    def __init__(self) -> None:
        self.writes: list[dict] = []
        self.logged_in = False
        self.docs = json.loads(json.dumps(LIVE_DOCS))  # private deep copy
        self.commands: list[str] = []
        self.verbs: list[str] = []
        self.records: list[dict] = []
        self.passwords: list[tuple] = []
        self.cleared_profiles: list = []
        self.added_profiles: list[dict] = []
        self.domain_items: list[tuple[int, bytes]] = []
        self.synced = None
        self.info_override: ChargerInfo | None = None
        self.login_error: httpx.HTTPError | None = None
        self.username = "admin"
        self.password = "secret"
        self.uploads: list[bytes] = []
        self.on_upload_progress = None

    def login(self) -> None:
        if self.login_error is not None:
            raise self.login_error
        self.logged_in = True

    def logout(self) -> None:
        pass

    def close(self) -> None:
        pass

    def basic_info(self) -> ChargerInfo:
        if self.info_override is not None:
            return self.info_override
        return INFO

    def fetch_log(self, offset: int = 0, lines: int | None = None) -> str:
        """Model the charger's paging: `offset` counts lines back from the newest.

        ``docs["/api/log"]`` is chronological (oldest first, ids ascending),
        as the buffer is; a page holds ``log_page_lines`` lines, runs
        oldest-first, and offsets past the end return nothing.
        """
        stored = self.docs["/api/log"]
        page = lines or self.log_page_lines
        end = len(stored) - offset
        if end <= 0:
            return ""
        return "\n".join(stored[max(0, end - page) : end])

    def fetch_transactions(self, offset: int = 0xFFFFFFFF) -> str:
        """Page the fake transaction database the way the charger does."""
        stored = self.docs.get("/api/transactions", [])
        if not stored:
            return "empty transaction database"
        older = [ln for ln in stored if int(ln.split("_")[0]) < offset]
        return "\n".join(older[-2:]) if older else ""

    def erase_transactions(self, is_ahp: bool = False) -> None:
        self.erased = True

    def fetch_whitelist(self, index: int = 0) -> str:
        entries = self.docs.get("/api/whitelist", [])
        return json.dumps(
            {
                "version": 1,
                "whitelist": entries[index : index + 2] if index < len(entries) else [],
            }
        )

    def whitelist_verb(self, query: str) -> None:
        self.verbs.append(query)

    def add_tag(self, record: dict) -> None:
        self.records.append(dict(record))

    def set_password(self, new_password: str) -> None:
        self.passwords.append(("set", new_password, None))

    def set_temporary_password(self, new_password: str, hours: int) -> None:
        self.passwords.append(("temporary", new_password, hours))

    def reset_password(self, code: str) -> None:
        if self.recovery_error is not None:
            raise self.recovery_error
        self.passwords.append(("recover", code, None))

    def send_command(self, command: str, timeout: float | None = None) -> None:
        self.commands.append(command)

    # --- the firmware channel (both a firmware image and a logo go through it)

    def firmware_status(self, timeout: float | None = None) -> tuple[bool, int]:
        from alfenctl.firmware import FW_UPDATE_DONE

        self.commands.append("firmware_status")
        return self.upload_in_progress, FW_UPDATE_DONE

    def upload_firmware(self, data: bytes) -> None:
        self.uploads.append(data)
        if self.on_upload_progress is not None:
            self.on_upload_progress(len(data), len(data), 1.0)

    def commit_firmware(self) -> None:
        self.commands.append("commit_firmware")

    def reboot(self, is_ahp: bool = False) -> None:
        self.commands.append("reboot" if not is_ahp else "reset?type=hard")

    def clear_settings(self, is_ahp: bool = False) -> None:
        self.commands.append("clear-settings")

    def clear_personal_data(self) -> None:
        self.commands.append("clear-personal-data")

    def categories(self) -> list[str]:
        return list(self.docs["/api/categories"]["categories"])

    def fetch_properties(self, category: str | None = None):
        from alfenctl.charger import parse_live_property

        entries = list(self.docs["/api/prop"]["properties"])
        if category in ("states", "meter1", "temp"):
            entries = self.docs.get("/api/status-props", [])
        return [lp for lp in (parse_live_property(p) for p in entries) if lp]

    def all_properties(self, on_category=None):
        if on_category is not None:
            on_category(1, 1, "everything")
        return self.fetch_properties(None)

    def fetch_properties_by_ids(self, keys):
        from alfenctl.charger import parse_live_property

        wanted = set(keys)
        return [
            lp
            for lp in (
                parse_live_property(p) for p in self.docs["/api/prop"]["properties"]
            )
            if lp.key in wanted
        ]

    def write_properties(self, writes):
        self.writes.append(dict(writes))
        for key, (value, dtype) in writes.items():
            for p in self.docs["/api/prop"]["properties"]:
                from alfenctl.charger import parse_live_property

                lp = parse_live_property(p)
                if lp.key == key:
                    p["value"] = value

    def wifi_scan(self) -> str:
        return json.dumps({"scan_results": self.docs.get("/api/wifiscan", [])})

    def set_datetime(self, is_ahp: bool = False, when=None):
        self.synced = when or datetime.now(timezone.utc)
        return self.synced

    def set_domain_item(self, item_type: int, data: bytes) -> None:
        self.domain_items.append((item_type, data))

    def set_end_user_pin(self, pin: str) -> None:
        self.end_user_pin = pin

    def disable_end_user_access(self) -> None:
        self.end_user_pin = None

    def properties(self, category: str = "generic"):
        from alfenctl.charger import parse_live_property

        entries = self.docs.get(f"/api/{category}", [])
        return {
            lp.key: lp.value for lp in (parse_live_property(p) for p in entries) if lp
        }

    charging_profile_error: httpx.HTTPStatusError | None = None

    def _maybe_raise_charging_profile_error(self) -> None:
        if self.charging_profile_error is not None:
            raise self.charging_profile_error

    def fetch_charging_profile_ids(self):
        self._maybe_raise_charging_profile_error()
        return FakeResponse(self.docs.get("/api/chargingprofiles-ids", "{}"))

    def fetch_charging_profile(self, profile_id: int):
        self._maybe_raise_charging_profile_error()
        return FakeResponse(
            self.docs.get("/api/chargingprofiles", {}).get(str(profile_id), "{}")
        )

    def clear_charging_profile(self, profile_id) -> None:
        self._maybe_raise_charging_profile_error()
        self.cleared_profiles.append(profile_id)

    def add_charging_profile(self, profile: dict):
        self._maybe_raise_charging_profile_error()
        self.added_profiles.append(profile)
        return FakeResponse("{}")


class FakeResponse:
    """Stands in for the bits of httpx.Response the new commands read."""

    def __init__(self, text: str) -> None:
        self.text = text


# The CLI is a package: a name like `discover` is imported into each module
# that uses it, so patching it means patching every one of those bindings.
# These helpers keep that knowledge in one place instead of in every test.
DISCOVER_SITES = (
    "alfenctl.cli.target",
    "alfenctl.cli.commands.stations",
    "alfenctl.cli.commands.scn",
)


def patch_discover(monkeypatch, fn) -> None:
    """Replace discovery everywhere the CLI reaches for it."""
    for module in DISCOVER_SITES:
        monkeypatch.setattr(f"{module}.discover", fn)


CHARGER_SITES = ("alfenctl.cli.target", "alfenctl.cli.commands.scn")


def patch_charger(monkeypatch, ctor) -> None:
    """Replace the charger client wherever the CLI opens one.

    `scn` is the one group that opens sessions of its own, to the peers.
    """
    for module in CHARGER_SITES:
        monkeypatch.setattr(f"{module}.AlfenCharger", ctor)


def patch_wait_until_back(monkeypatch, fn) -> None:
    """Replace the post-reboot wait; every command goes through the one helper."""
    monkeypatch.setattr("alfenctl.cli.report.wait_until_back", fn)


@pytest.fixture
def fake_charger(monkeypatch) -> FakeCharger:
    fc = FakeCharger()
    patch_charger(monkeypatch, lambda *a, **k: fc)
    return fc


def status_error(code: int, body: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://1.2.3.4/api/prc")
    return httpx.HTTPStatusError(
        "refused",
        request=request,
        response=httpx.Response(code, text=body, request=request),
    )


# --- the web UI ------------------------------------------------------------------------------
# The web tests run against their own fake, in webfake.py: it stands in for a
# charger one level up, where the HTTP protocol has already been dealt with.


@pytest.fixture
def worker():
    """A started station worker over a fake charger, stopped on the way out."""
    from webfake import make_worker

    worker = make_worker()
    worker.start()
    yield worker
    worker.stop()


@pytest.fixture
def context(worker):
    """An API context over the fake worker, polling the way the server does."""
    from alfenctl.web import api

    ctx = api.Context(worker=worker, config=None)
    worker.set_poll_fn(api.make_poll(ctx))
    return ctx
