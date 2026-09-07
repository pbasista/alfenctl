"""The charger the web tests run against, and the worker wired to it.

Nothing here reaches a station: :class:`FakeCharger` answers the calls
``web/session.py`` and ``web/api.py`` actually make, out of values the test
can edit, and records what was written to it.  The ``worker`` and
``context`` fixtures in ``conftest.py`` build on :func:`make_worker`.

This is the web layer's own fake -- the one in ``conftest.py`` stands in
for the HTTP protocol a level below, which the web layer never speaks.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from alfenctl.charger import ChargerInfo, LiveProperty
from alfenctl.discovery import Station
from alfenctl.web import api
from alfenctl.web.events import Broadcaster
from alfenctl.web.session import StationWorker, Target


STATION = Station(ip="10.0.0.7", port=443, hostname="ALF-ACE0781464.local.")
INFO = ChargerInfo(
    object_id="ACE0781464",
    identity="garage",
    model="NG910",
    family="NG9xx",
    firmware="6.4.0-4210",
    firmware_version=(6, 4, 0),
    sockets=1,
)

# id, sub-id, value, type, access, category
LIVE = [
    ("2501_1", (0x2501, 1), 2, 5, 1, "states"),
    ("2501_4", (0x2501, 4), 1, 5, 1, "states"),
    ("2221_16", (0x2221, 0x16), 3450.0, 8, 1, "meter1"),
    ("2221_3", (0x2221, 0x3), 230.5, 8, 1, "meter1"),
    # The lifetime total is not in the walk on a real station; the fake keeps
    # it out of `meter1` too, so `status.collect`'s extra ids= read is what
    # finds it here as well.
    ("2221_22", (0x2221, 0x22), 812500.0, 8, 1, ""),
    ("2201_0", (0x2201, 0), 24.5, 8, 1, "temp"),
    ("2202_0", (0x2202, 0), -25.0, 8, 0, "temp"),
    ("2203_0", (0x2203, 0), 60.0, 8, 0, "temp"),
    ("2062_0", (0x2062, 0), 16, 5, 0, "generic"),
    ("2129_0", (0x2129, 0), 16.0, 8, 0, "generic"),
    ("2061_1", (0x2061, 1), 1, 2, 0, "generic"),
    ("2061_2", (0x2061, 2), 60, 2, 0, "generic"),
    ("2059_0", (0x2059, 0), 1788000000000, 27, 0, "generic"),
    ("206E_0", (0x206E, 0), 60, 3, 0, "generic"),
    # The display descriptor: this fake station has a 320x165 screen, which
    # is what lets it be sent a logo (see `logo.read_display`).
    ("3260_1", (0x3260, 1), 320, 6, 1, "generic"),
    ("3260_3", (0x3260, 3), 320, 6, 1, "generic"),
    ("3260_4", (0x3260, 4), 165, 6, 1, "generic"),
    # The license trio.  On a real NG910 these answer only to explicit
    # ids= reads -- no category walk lists them -- and `collect` adds them
    # to the whole-charger walk and to nothing else.  Here they are plain
    # generic rows, so a category read of "generic" finds them the way any
    # walk would.
    ("21A0_0", (0x21A0, 0), "ABC123", 9, 1, "generic"),
    ("21A1_0", (0x21A1, 0), "0011.2233.4455.6677", 9, 1, "generic"),
    ("21A2_0", (0x21A2, 0), 3, 7, 1, "generic"),
    # The installation settings (see `alfenctl.setup`): position, language,
    # uptime, load balancing and the on-screen price, exactly as a real
    # NG910 answers them.
    ("205C_1", (0x205C, 1), 48.7347412109375, 8, 2, ""),
    ("205C_2", (0x205C, 2), 21.954866409301758, 8, 2, ""),
    ("205D_0", (0x205D, 0), "en_GB", 9, 2, ""),
    # Milliseconds, whatever the register's name says -- see MS_PER_SECOND
    # in `alfenctl.setup`.  This is the reading a live NG910 gave: three and
    # a half hours up, and 144 days if it is mistaken for seconds.
    ("2060_0", (0x2060, 0), 12484257, 5, 1, ""),
    ("2064_0", (0x2064, 0), 3, 5, 2, ""),
    ("2065_1", (0x2065, 1), 1, 5, 2, ""),
    ("3262_1", (0x3262, 1), "EUR", 9, 2, ""),
    ("3262_2", (0x3262, 2), 0, 8, 2, ""),
    ("3262_3", (0x3262, 3), 0.2, 8, 2, ""),
    ("3262_4", (0x3262, 4), 0, 8, 2, ""),
    # A register no source describes -- EDS, the Windows app, My Eve, the
    # Home Assistant integration -- so the browser has a row to badge
    # "purpose unknown" and the JSON a `known: false` to say it with.
    ("3251_0", (0x3251, 0), 0, 6, 1, "generic"),
    # The tilt sensor's live axes and stored setpoints (see alfenctl.tilt).
    ("2207_0", (0x2207, 0), 12, 5, 1, "temp"),
    ("2208_0", (0x2208, 0), -4, 5, 1, "temp"),
    ("2209_0", (0x2209, 0), 238, 5, 1, "temp"),
    ("2210_0", (0x2210, 0), 12, 5, 0, "temp"),
    ("2211_0", (0x2211, 0), -4, 5, 0, "temp"),
    ("2212_0", (0x2212, 0), 238, 5, 0, "temp"),
    # The master tag (0x2400 subs 1-2, by explicit ids= only).
    ("2400_1", (0x2400, 1), 1, 5, 1, ""),
    ("2400_2", (0x2400, 2), "04MASTER", 9, 1, ""),
    # SCN membership (0x2180): an empty name means "not in a network".
    ("2180_1", (0x2180, 1), "", 9, 0, ""),
    # The charging-profile override (0x3278 subs) and its random delay.
    ("3278_1", (0x3278, 1), 0, 5, 0, ""),
    ("21B9_0", (0x21B9, 0), 600, 5, 0, ""),
]


def _props(keep=None) -> list[LiveProperty]:
    return [
        LiveProperty(
            id=id_, key=key, value=value, data_type=dt, access=access, category=cat
        )
        for id_, key, value, dt, access, cat in LIVE
        if keep is None or cat == keep
    ]


class FakeCharger:
    """The charger surface the web layer actually touches."""

    def __init__(self) -> None:
        self.logged_in = 0
        self.logged_out = 0
        self.closed = 0
        self.writes: list[dict] = []
        self.commands: list[str] = []
        self.uploads: list[bytes] = []
        self.fail_with: Exception | None = None
        self.on_upload_progress = None
        self._whitelist: list[dict] = [
            {"tag": "04A1B2C3D4", "parent": "", "status": 1, "expiryDate": 0},
            {"tag": "04DEADBEEF", "parent": "", "status": 1, "expiryDate": 0},
        ]

    # The backup's XML shapes quote the station's address in their
    # header, like a real charger's own settings file does.
    station = STATION

    def login(self) -> None:
        self.logged_in += 1

    def logout(self) -> None:
        self.logged_out += 1

    def close(self) -> None:
        self.closed += 1

    def basic_info(self) -> ChargerInfo:
        if self.fail_with is not None:
            raise self.fail_with
        return INFO

    def categories(self) -> list[str]:
        return ["generic", "states", "meter1", "temp"]

    def fetch_properties(self, category=None) -> list[LiveProperty]:
        return _props(category)

    def fetch_properties_by_ids(self, keys) -> list[LiveProperty]:
        wanted = set(keys)
        return [p for p in _props() if p.key in wanted]

    def properties(self, category="generic") -> dict:
        return {p.key: p.value for p in _props(category)}

    def all_properties(self, on_category=None) -> list[LiveProperty]:
        if on_category is not None:
            on_category(1, 1, "everything")
        return _props()

    def write_properties(self, payload) -> None:
        self.writes.append(dict(payload))

    def fetch_log(self, offset: int = 0, lines=None) -> str:
        return (
            "4294_2026-08-29T12:41:53.000Z:INFO:main.c:12:started\n"
            "4295_2026-08-29T12:41:54.001Z:ERROR:fw.c:388:rejected"
        )

    def reboot(self, is_ahp: bool = False) -> None:
        self.commands.append("reboot")

    def set_datetime(self, is_ahp: bool = False, when=None):
        self.commands.append("date")
        return when or datetime.now(timezone.utc)

    def firmware_status(self, timeout=None):
        return False, 0

    def commit_firmware(self) -> None:
        self.commands.append("forcefirmwarepermanent")

    def upload_firmware(self, data: bytes) -> None:
        if self.on_upload_progress is not None:
            self.on_upload_progress(len(data) // 2, len(data), 0.5)
            self.on_upload_progress(len(data), len(data), 1.0)
        self.uploads.append(data)

    # --- the surface the panel endpoints touch ------------------------------------------
    def fetch_whitelist(self, index: int = 0) -> str:
        import json as _json

        if index > 0:
            return "{}"
        return _json.dumps({"whitelist": list(self._whitelist)})

    def whitelist_verb(self, query: str) -> None:
        self.commands.append(f"whitelist?{query}")
        if query.startswith("remove="):
            gone = query.split("=", 1)[1]
            self._whitelist = [t for t in self._whitelist if t["tag"] != gone]
        elif query == "clear":
            self._whitelist = []

    def add_tag(self, record) -> None:
        self.commands.append(f"addtag:{record.get('tagid')}")
        entry = {
            "tag": str(record.get("tagid")),
            "parent": str(record.get("parentid") or ""),
            "status": int(record.get("status") or 1),
            "expiryDate": 0,
        }
        self._whitelist = [t for t in self._whitelist if t["tag"] != entry["tag"]] + [
            entry
        ]

    def fetch_transactions(self, offset: int = 0xFFFFFFFF) -> str:
        if offset == 0:
            return "empty transaction database"
        # The charger's own grammar: one <offset>_<text> line per record,
        # tx records comma-separated as "id, socket<n>, <start half>[, <stop half>]"
        # -- see transactions.parse_record for the shapes.
        return (
            "0_tx: id = 1A, socket1, 2026-08-01 10:00:00 100.5kWh 04A1B2C3D4 N, "
            "2026-08-01 11:00:00 205.5kWh 04A1B2C3D4 N\n"
            "1_tx: id = 1B, socket1, 2026-08-02 09:00:00 300kWh 04A1B2C3D4 N, "
            "2026-08-02 09:30:00 310.25kWh 04A1B2C3D4 N\n"
        )

    def wifi_scan(self) -> str:
        return (
            '{"scan_results": ['
            '{"ssid": "home", "signal_dbm": -48, "security": 4194308, "band": 1},'
            '{"ssid": "neighbour", "signal_dbm": -72, "security": 0, "band": 1}'
            "]}"
        )

    def set_domain_item(self, item_type: int, data: bytes) -> None:
        self.commands.append(f"domain:{item_type}:{len(data)}b")

    def send_command(self, command: str, timeout: float | None = None) -> None:
        self.commands.append(f"cmd:{command}")

    def clear_settings(self, is_ahp: bool = False) -> None:
        self.commands.append("eepromx erase config")

    def clear_personal_data(self) -> None:
        self.commands.append("clearpersonaldata")

    def erase_transactions(self, is_ahp: bool = False) -> None:
        self.commands.append("txerase")

    def set_password(self, new_password: str) -> None:
        self.commands.append("password:set")

    def set_temporary_password(self, new_password: str, hours: int) -> None:
        self.commands.append(f"temporarypassword:{hours}h")

    def reset_password(self, code: str) -> None:
        self.commands.append(f"password:reset:{code}")

    def set_end_user_pin(self, pin: str) -> None:
        self.commands.append(f"enduserpin:{pin or 'empty'}")

    def disable_end_user_access(self) -> None:
        self.commands.append("enduserpin:disable")

    def fetch_charging_profile_ids(self):
        class _Reply:
            text = '{"ChargingProfileIDs": [-19061964]}'

        return _Reply()

    def fetch_charging_profile(self, profile_id: int):
        # ICUChargingProfiles.GetChargingProfile's version-2 reply shape,
        # as charging_profiles.parse_profiles expects it.
        class _Reply:
            text = (
                '{"version": 2, "Profile": [{"connectorId": 1, '
                '"csChargingProfiles": [{'
                '"chargingProfileId": -19061964, '
                '"chargingProfileKind": "Recurring", '
                '"chargingProfilePurpose": "ChargePointMaxProfile", '
                '"stackLevel": 0, '
                '"chargingSchedule": {'
                '"chargingRateUnit": "A", '
                '"startSchedule": "2026-01-05T00:00:00Z", '
                '"chargingSchedulePeriod": [{"startPeriod": 0, "limit": 32}]}}]}]}'
            )

        return _Reply()

    def clear_charging_profile(self, profile_id) -> None:
        self.commands.append(f"chargingprofiles:clear:{profile_id}")

    def add_charging_profile(self, profile) -> None:
        self.commands.append("chargingprofiles:add")


def make_worker() -> StationWorker:
    """A worker over a fresh :class:`FakeCharger`, not yet started.

    The charger is hung on the worker as ``worker.charger`` so a test can
    see what the code under test did to it.
    """
    charger = FakeCharger()
    worker = StationWorker(
        Target(station=STATION, username="admin", password="secret", label="garage"),
        Broadcaster(),
        poll_interval=0.05,
        idle_timeout=0.3,
        charger_factory=lambda target: charger,
    )
    worker.charger = charger
    return worker


def call(ctx, method, path, body=None, **query):
    """Run one API handler the way the server would."""
    route = api.ROUTES[(method, path)]
    request = api.Request(
        method=method,
        path=path,
        query={k: str(v) for k, v in query.items()},
        body=json.dumps(body).encode() if body is not None else b"",
    )
    response = route.handler(ctx, request)
    return response.status, json.loads(response.body or b"null")


def wait_for(predicate, timeout=3.0):
    """Spin until ``predicate`` holds, so tests do not race the worker thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False
