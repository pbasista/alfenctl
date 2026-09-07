"""Tests for log-line parsing, the dated download and the range probe."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from alfenctl import logs

# One line every 10 minutes, ids stepping by the charger's 128-byte record
# size, oldest first -- the order the buffer holds them in.
BASE = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
FIRST_ID = 1_000_000


def make_lines(count: int, *, start: datetime = BASE, step_s: int = 600) -> list[str]:
    """Build ``count`` synthetic log lines, oldest first."""
    return [
        f"{FIRST_ID + i * 128}_"
        f"{(start + timedelta(seconds=i * step_s)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z"
        f":INFO:taskMain.c:{100 + i}:line {i}"
        for i in range(count)
    ]


class FakeLog:
    """A charger log buffer that pages exactly like the real ``/api/log``."""

    def __init__(self, lines: list[str], page: int = 8) -> None:
        self.lines = lines  # chronological, oldest first
        self.page = page
        self.offsets: list[int] = []

    def fetch_log(self, offset: int = 0, lines: int | None = None) -> str:
        self.offsets.append(offset)
        page = lines or self.page
        end = len(self.lines) - offset
        if end <= 0:
            return ""
        return "\n".join(self.lines[max(0, end - page) : end])


class ClampingLog(FakeLog):
    """A charger that clamps an over-large ``offset`` instead of returning nothing."""

    def fetch_log(self, offset: int = 0, lines: int | None = None) -> str:
        return super().fetch_log(min(offset, max(0, len(self.lines) - 1)), lines)


# --- parsing -----------------------------------------------------------------------------


def test_parse_log_line_splits_id_time_and_strips_ansi() -> None:
    line = logs.parse_log_line(
        "2187008_2026-08-29T13:26:34.996Z:USER:updatefirmware.:309:\x1b[31mboom\x1b[0m"
    )
    assert line.id == 2187008
    assert line.time == datetime(2026, 8, 29, 13, 26, 34, 996000, tzinfo=timezone.utc)
    assert line.text.endswith(":309:boom")
    assert "\x1b" not in line.text


def test_parse_log_line_keeps_untagged_lines() -> None:
    """A line without the id_timestamp prefix survives, with no id and no time."""
    line = logs.parse_log_line("Communication Error")
    assert line.id is None and line.time is None
    assert line.text == "Communication Error"


def test_parse_page_drops_blank_lines() -> None:
    assert len(logs.parse_page("\n".join(make_lines(3)) + "\n\n")) == 3


# --- --since parsing ---------------------------------------------------------------------


def test_parse_since_all_means_no_cutoff() -> None:
    assert logs.parse_since("all") is None
    assert logs.parse_since("ALL") is None


def test_parse_since_today_is_local_midnight() -> None:
    now = datetime(2026, 9, 1, 15, 30, tzinfo=timezone.utc)
    cutoff = logs.parse_since("today", now=now)
    assert cutoff is not None
    assert cutoff.astimezone().hour == 0
    assert cutoff.astimezone().date() == now.astimezone().date()


def test_parse_since_yesterday_is_a_day_earlier() -> None:
    now = datetime(2026, 9, 1, 15, 30, tzinfo=timezone.utc)
    today = logs.parse_since("today", now=now)
    assert today is not None
    assert today - logs.parse_since("yesterday", now=now) == timedelta(days=1)


@pytest.mark.parametrize(
    "spec, delta",
    [
        ("45m", timedelta(minutes=45)),
        ("12h", timedelta(hours=12)),
        ("7d", timedelta(days=7)),
        ("3w", timedelta(weeks=3)),
    ],
)
def test_parse_since_relative_spans(spec: str, delta: timedelta) -> None:
    now = datetime(2026, 9, 1, 15, 30, tzinfo=timezone.utc)
    assert logs.parse_since(spec, now=now) == now - delta


@pytest.mark.parametrize(
    "spec", ["2026-08-25", "25.08.2026", "2026-08-25T00:00", "2026-08-25 00:00"]
)
def test_parse_since_absolute_forms_agree(spec: str) -> None:
    """Every accepted absolute spelling of the same local midnight lands together."""
    assert logs.parse_since(spec) == logs.parse_since("2026-08-25")


def test_parse_since_honours_an_explicit_offset() -> None:
    assert logs.parse_since("2026-08-25T06:00:00+00:00") == datetime(
        2026, 8, 25, 6, 0, tzinfo=timezone.utc
    )


@pytest.mark.parametrize("spec", ["", "last tuesday", "5y", "2026-13-01"])
def test_parse_since_rejects_nonsense(spec: str) -> None:
    with pytest.raises(logs.SinceError):
        logs.parse_since(spec)


# --- download ----------------------------------------------------------------------------


def test_download_all_returns_chronological_order() -> None:
    """Pages arrive newest-first; the result must read oldest-first."""
    source = FakeLog(make_lines(20), page=8)
    result = logs.download(source)
    assert result.exhausted and not result.truncated
    assert [ln.id for ln in result.lines] == sorted(ln.id for ln in result.lines)
    assert result.lines[0].text.endswith("line 0")
    assert result.lines[-1].text.endswith("line 19")
    assert result.fetched == 20 and result.dropped == 0


def test_download_stops_once_a_whole_page_predates_the_cutoff() -> None:
    """We keep only what was asked for, and stop paging soon after."""
    source = FakeLog(make_lines(40), page=8)  # 40 lines, 10 min apart
    since = BASE + timedelta(hours=5)  # keeps lines 30..39
    result = logs.download(source, since)
    assert all(ln.time >= since for ln in result.lines)
    assert [ln.text.split()[-1] for ln in result.lines] == [
        str(i) for i in range(30, 40)
    ]
    assert result.pages < 5  # not the whole buffer: it stopped early
    assert result.dropped > 0  # the last page straddled the cutoff


def test_download_does_not_stop_on_a_single_stale_timestamp() -> None:
    """A post-reboot clock jump inside a page must not end the download."""
    lines = make_lines(24)
    # The charger rebooted: one line carries the firmware build date.
    lines[20] = lines[20].replace("2026-08-29T03", "2026-07-31T07")
    source = FakeLog(lines, page=8)
    result = logs.download(source, BASE + timedelta(hours=1))
    assert result.exhausted  # walked to the end of the buffer, not tripped at line 20
    assert result.fetched == 24


def test_download_survives_a_charger_that_ignores_offset() -> None:
    """Repeated pages are recognised as the end, not paged forever."""

    class StuckLog(FakeLog):
        def fetch_log(self, offset: int = 0, lines: int | None = None) -> str:
            return super().fetch_log(0, lines)

    result = logs.download(StuckLog(make_lines(20), page=8))
    assert result.pages == 1 and result.exhausted and not result.truncated


def test_download_stops_on_a_page_of_untagged_lines() -> None:
    """Lines with no record id can't be deduped, so they must not loop us."""

    class NoisyLog(FakeLog):
        def fetch_log(self, offset: int = 0, lines: int | None = None) -> str:
            return "Communication Error"

    result = logs.download(NoisyLog([], page=8), max_pages=50)
    assert result.pages == 0 and result.exhausted and not result.truncated


def test_download_reports_the_page_cap() -> None:
    result = logs.download(FakeLog(make_lines(40), page=8), max_pages=2)
    assert result.truncated and not result.exhausted
    assert result.pages == 2


def test_download_reports_the_span_it_covered() -> None:
    result = logs.download(FakeLog(make_lines(10), page=4))
    assert result.oldest == BASE
    assert result.newest == BASE + timedelta(minutes=90)


# --- range probe -------------------------------------------------------------------------


def test_probe_range_finds_the_oldest_entry() -> None:
    source = FakeLog(make_lines(100), page=8)
    span = logs.probe_range(source)
    assert span is not None and span.exact
    assert span.oldest == BASE
    assert span.newest == BASE + timedelta(minutes=99 * 10)
    assert span.page_lines == 8
    assert abs(span.lines - 100) <= 8  # exact to within one page


def test_probe_range_is_cheaper_than_walking_the_buffer() -> None:
    source = FakeLog(make_lines(4000), page=8)  # 500 pages
    span = logs.probe_range(source)
    assert span is not None and span.oldest == BASE
    assert span.requests < 25  # ~2*log2(500), not 500


def test_probe_range_handles_a_charger_that_clamps_offset() -> None:
    """No empty page ever comes back; the id floor still marks the end."""
    source = ClampingLog(make_lines(60), page=8)
    span = logs.probe_range(source)
    assert span is not None and span.oldest == BASE


def test_probe_range_on_an_empty_log() -> None:
    assert logs.probe_range(FakeLog([], page=8)) is None


def test_probe_range_reports_when_it_hits_its_cap() -> None:
    span = logs.probe_range(FakeLog(make_lines(200), page=8), max_pages=2)
    assert span is not None and not span.exact


# --- formatting --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "delta, expected",
    [
        (timedelta(seconds=5), "just now"),
        (timedelta(minutes=42), "42m ago"),
        (timedelta(hours=4, minutes=39), "4h39m ago"),
        (timedelta(days=3, hours=12), "3.5 days ago"),
        (timedelta(seconds=-5), "in the future"),
    ],
)
def test_format_age(delta: timedelta, expected: str) -> None:
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    assert logs.format_age(now - delta, now=now) == expected


def test_format_time_and_age_handle_a_missing_stamp() -> None:
    assert logs.format_time(None) == "unknown"
    assert logs.format_age(None) == ""


def test_format_time_renders_local_time() -> None:
    stamp = datetime(2026, 8, 29, 13, 26, 34, tzinfo=timezone.utc)
    assert logs.format_time(stamp) == stamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
