"""Tests for transaction-database parsing, paging and session folding."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from alfenctl import transactions as tx

# Records in the shapes ICUTransactionItem parses, oldest first.
COMPLETE = (
    "1024_tx: id = 0000A1B2, socket1, "
    "2026-08-29 08:00:00 1200.500kWh 04A1B2C3D4E5 Y, "
    "2026-08-29 11:30:00 1215.750kWh 04A1B2C3D4E5 3 Y"
)
RUNNING_START = (
    "2048_txstart2: id = 0000C3D4, socket2, "
    "2026-08-30 09:15:00 900.000kWh 04FFEE1122 17 1 N"
)
STOP_FOR_IT = (
    "3072_txstop2: id = 0000C3D4, socket2, "
    "2026-08-30 12:45:00 910.250kWh 04FFEE1122 16 5 N"
)
METER_VALUE = "4096_mv: socket 1, 2026-08-29 09:00:00 1205.000kWh regular Y"
STATUS = (
    "5120_sn3: socket 1, 2026-08-29 08:00:01 Available Charging state changed 1 1 Y"
)
SECURITY = "6144_se: 2026-08-29 07:59:00: 5 (Y)"
CLOCK = "7168_dto: -3600"
RESERVATION = "8192_rs: #42 tag 04AABBCC on socket 1, at 2026-08-31 10:00:00"


def test_parse_complete_transaction() -> None:
    r = tx.parse_record(COMPLETE)
    assert r is not None
    assert r.kind == "transaction"
    assert r.offset == 1024
    assert r.transaction_id == 0xA1B2
    assert r.socket == 1
    assert r.start_time == datetime(2026, 8, 29, 8, 0, 0)
    assert r.stop_time == datetime(2026, 8, 29, 11, 30, 0)
    assert r.start_meter_kwh == 1200.5
    assert r.stop_meter_kwh == 1215.75
    assert r.start_tag == "04A1B2C3D4E5"
    assert r.stop_reason == "ev-disconnected"  # code 3
    assert r.energy_kwh == 15.25
    assert r.duration == timedelta(hours=3, minutes=30)


def test_parse_ocpp2_start_and_stop() -> None:
    start = tx.parse_record(RUNNING_START)
    stop = tx.parse_record(STOP_FOR_IT)
    assert start is not None and stop is not None
    assert start.kind == "start" and stop.kind == "stop"
    assert start.transaction_id == stop.transaction_id == 0xC3D4
    assert start.trigger_reason == "remote-start"  # 17
    assert start.charging_state == "charging"  # 1
    assert stop.trigger_reason == "remote-stop"  # 16
    assert stop.charging_state == "idle"  # 5
    assert start.start_to_send is False  # trailing N


def test_parse_other_record_kinds() -> None:
    assert tx.parse_record(METER_VALUE).kind == "meter-value"
    assert tx.parse_record(METER_VALUE).start_meter_kwh == 1205.0
    assert tx.parse_record(METER_VALUE).extra == "regular"
    assert tx.parse_record(STATUS).kind == "status"
    assert tx.parse_record(SECURITY).security_event == "start-up-device"  # 5
    assert tx.parse_record(CLOCK).kind == "clock-offset"
    assert tx.parse_record(CLOCK).extra == str(timedelta(seconds=-3600))
    assert tx.parse_record(RESERVATION).kind == "reservation"


def test_unknown_record_still_comes_out() -> None:
    """Firmware we have not seen must not lose data."""
    r = tx.parse_record("9999_weird: something entirely new")
    assert r is not None
    assert r.kind == "unknown"
    assert r.raw == "weird: something entirely new"


def test_parse_record_rejects_junk() -> None:
    assert tx.parse_record("") is None
    assert tx.parse_record("no underscore here") is None
    assert tx.parse_record("notanumber_tx: ...") is None


def test_parse_page_strips_the_firmware_envelope() -> None:
    """Newer firmware wraps the text in JSON and adds AP;...; prefixes."""
    page = '{"version":1,' + COMPLETE + "\n" + "AP;xx; " + METER_VALUE + "}\n\n"
    records = tx.parse_page(page)
    assert [r.kind for r in records] == ["transaction", "meter-value"]


def test_missing_tag_is_none_not_the_literal_null() -> None:
    r = tx.parse_record(
        "1_txstop: id = 0000FFFF, socket1, 2026-08-29 11:30:00 5.0kWh (null) Y"
    )
    assert r.stop_tag is None


# --- Paging ------------------------------------------------------------------------------


class FakeDb:
    """A transaction database that pages the way the charger's does."""

    def __init__(self, lines: list[str], page: int = 2) -> None:
        self.lines = lines  # oldest first
        self.page = page
        self.offsets: list[int] = []

    def fetch_transactions(self, offset: int = tx.NEWEST_OFFSET) -> str:
        self.offsets.append(offset)
        # Records strictly older than `offset`, newest `page` of them.
        older = [ln for ln in self.lines if int(ln.split("_")[0]) < offset]
        if not older:
            return ""
        return "\n".join(older[-self.page :])


ALL_LINES = [COMPLETE, RUNNING_START, STOP_FOR_IT, METER_VALUE, STATUS, SECURITY]


def test_download_pages_backwards_to_the_start() -> None:
    db = FakeDb(ALL_LINES, page=2)
    result = tx.download(db)
    assert len(result.records) == len(ALL_LINES)
    assert db.offsets[0] == tx.NEWEST_OFFSET
    assert db.offsets == sorted(db.offsets, reverse=True)  # always further back


def test_download_returns_records_oldest_first() -> None:
    result = tx.download(FakeDb(ALL_LINES, page=2))
    times = [r.time for r in result.records if r.time]
    assert times == sorted(times)


def test_download_reports_an_empty_database() -> None:
    class Empty:
        def fetch_transactions(self, offset: int = 0) -> str:
            return "empty transaction database"

    result = tx.download(Empty())
    assert result.empty and not result.records


def test_download_stops_on_a_repeated_page() -> None:
    class Stuck(FakeDb):
        def fetch_transactions(self, offset: int = tx.NEWEST_OFFSET) -> str:
            return "\n".join(self.lines[-2:])

    result = tx.download(Stuck(ALL_LINES), max_pages=50)
    assert result.pages == 1 and not result.truncated


# --- Sessions ----------------------------------------------------------------------------


def test_sessions_folds_a_complete_transaction() -> None:
    sessions = tx.sessions([tx.parse_record(COMPLETE)])
    assert len(sessions) == 1
    s = sessions[0]
    assert s.complete and s.energy_kwh == 15.25
    assert s.average_kw == pytest.approx(4.36, abs=0.01)


def test_sessions_pairs_split_start_and_stop() -> None:
    records = [tx.parse_record(RUNNING_START), tx.parse_record(STOP_FOR_IT)]
    sessions = tx.sessions(records)
    assert len(sessions) == 1
    assert sessions[0].complete
    assert sessions[0].energy_kwh == 10.25
    assert sessions[0].socket == 2


def test_sessions_keeps_a_start_with_no_stop() -> None:
    """A session still running (or whose stop rolled out of the buffer)."""
    sessions = tx.sessions([tx.parse_record(RUNNING_START)])
    assert len(sessions) == 1
    assert not sessions[0].complete
    assert sessions[0].energy_kwh is None


def test_sessions_keeps_a_stop_with_no_start() -> None:
    sessions = tx.sessions([tx.parse_record(STOP_FOR_IT)])
    assert len(sessions) == 1
    assert sessions[0].stop_time is not None and sessions[0].start_time is None


def test_sessions_ignore_non_session_records() -> None:
    records = [tx.parse_record(x) for x in (METER_VALUE, STATUS, SECURITY, CLOCK)]
    assert tx.sessions(records) == []


def test_session_row_matches_the_column_list() -> None:
    row = tx.session_row(tx.sessions([tx.parse_record(COMPLETE)])[0])
    assert len(row) == len(tx.SESSION_COLUMNS)
    assert row[tx.SESSION_COLUMNS.index("energy_kwh")] == "15.250"
    assert row[tx.SESSION_COLUMNS.index("duration")] == "3:30:00"


def test_since_cutoff_filters_on_record_time() -> None:
    records = [tx.parse_record(x) for x in (COMPLETE, RUNNING_START)]
    kept = tx.since_cutoff(records, datetime(2026, 8, 30))
    assert len(kept) == 1 and kept[0].kind == "start"
    assert len(tx.since_cutoff(records, None)) == 2
