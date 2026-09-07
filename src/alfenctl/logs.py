"""The charger's own event log: parsing, dated download, and range probing.

``GET /api/log?offset=N`` returns one page of the charger's flash ring
buffer, counted in *lines back from the newest one*: ``offset=0`` is the
newest page, and each further page steps further into the past.  Lines look
like::

    2187008_2026-08-29T13:26:34.996Z:USER:updatefirmware.:309:Download progress:
    <id>_<ISO-8601 UTC>:<TYPE>:<source file>:<source line>:<text>

Within a page the lines run oldest-first; the ``id`` is the record's byte
offset in the buffer and decreases by a fixed step per line, so it -- not
the timestamp -- is the authoritative order.  Reversing the page order and
concatenating therefore yields a chronologically ordered log, which is what
the Windows app writes to file (``ICULanLog.WriteLoglinesToFile``).

Timestamps *can* run backwards across a reboot: the charger boots with its
RTC at the firmware build date and only jumps forward once ``date`` or NTP
sets it, so a handful of lines right after a restart may carry a stale
time.  :func:`download` therefore only stops paging once an entire page is
older than the cutoff, and never on a single stray line.

The charger offers no way to ask how far back its log reaches -- there is no
API call, no EDS property and no OCPP key for it (the app's own save dialog
just offers 1/3/7/21 days and "All" and finds out by hitting the end).
:func:`probe_range` recovers it anyway, by binary-searching ``offset`` for
the last page the charger still answers with; see its docstring.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol, Sequence

from alfenctl.errors import AlfenError
from alfenctl.progress import bar, end_live, fmt_duration, write_live

# The app's `&lines=` page size, sent on AHP >= 2.4 only (ICULanDevice
# .s_nMaxLogLines); other firmware picks the page size itself.
AHP_MAX_LOG_LINES = 10000
AHP_LINES_MIN_FIRMWARE = (2, 4, 0)

# Hard cap on pages walked by one download; a charger that ignores `offset`
# must not spin us.  At the 256-line pages an NG910 serves this is ~500k lines.
MAX_LOG_PAGES = 2000
# Hard cap on how deep probe_range() will look, in pages, for the same reason.
MAX_PROBE_PAGES = 1 << 20

# Don't redraw the download's live line more often than this.
PROGRESS_MIN_INTERVAL_S = 0.2

# "<id>_<ISO-8601 with milliseconds and a Z>:<rest>"; the app accepts an id of
# up to 20 digits before the underscore (ICULanLogLine's constructor).
_LINE_RE = re.compile(
    r"^(?P<id>\d{1,20})_(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})Z(?P<rest>:.*)?$",
    re.DOTALL,
)
# The charger colours some log text; the app strips exactly this.
_ANSI_RE = re.compile(r"\x1b\[(?:\d*;)?\d*m")

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400


class _LogSource(Protocol):
    """The one charger call this module needs (see ``AlfenCharger.fetch_log``)."""

    def fetch_log(self, offset: int = 0, lines: int | None = None) -> str: ...


# --- Log lines ---------------------------------------------------------------------------


# The kinds the firmware tags its lines with (``ICULanLogType``), which the
# app's log view filters on one at a time.  A line carries its kind between
# the timestamp and the source file: ``...Z:USER:updatefirmware.:309:...``.
LOG_TYPES = (
    "INFO",
    "WARNING",
    "ERROR",
    "COM",
    "USER",
    "RESET",
    "CONSOLE",
    "SECURITY",
)
_KIND_RE = re.compile(r"^:(?P<kind>[A-Z]+):")


@dataclass(frozen=True)
class LogLine:
    """One parsed log line.

    ``time`` is None for a line the charger emitted without the usual
    ``<id>_<timestamp>:`` prefix (a bare continuation line); such lines are
    never filtered out by a date cutoff, since there is nothing to compare.
    ``kind`` is the firmware's own tag for the line (:data:`LOG_TYPES`), None
    when the line does not carry one.
    """

    id: int | None
    time: datetime | None
    text: str  # the whole line, ANSI escapes removed
    kind: str | None = None


def parse_log_line(raw: str) -> LogLine:
    """Parse one raw log line; unparseable input still yields a text-only line."""
    text = _ANSI_RE.sub("", raw.rstrip("\r\n"))
    m = _LINE_RE.match(text)
    if not m:
        return LogLine(id=None, time=None, text=text)
    try:
        stamp = datetime.strptime(m["ts"], "%Y-%m-%dT%H:%M:%S.%f").replace(
            tzinfo=timezone.utc
        )
    except ValueError:  # a malformed date: keep the line, drop the time
        stamp = None
    kind_match = _KIND_RE.match(m["rest"] or "")
    return LogLine(
        id=int(m["id"]),
        time=stamp,
        text=text,
        kind=kind_match["kind"] if kind_match else None,
    )


def parse_page(page: str) -> list[LogLine]:
    """Parse one ``/api/log`` response body into lines, dropping blank ones."""
    return [parse_log_line(ln) for ln in page.splitlines() if ln.strip()]


def newest_time(lines: Sequence[LogLine]) -> datetime | None:
    """Return the latest timestamp in ``lines``, or None if none is dated."""
    stamps = [ln.time for ln in lines if ln.time is not None]
    return max(stamps) if stamps else None


def oldest_time(lines: Sequence[LogLine]) -> datetime | None:
    """Return the earliest timestamp in ``lines``, or None if none is dated."""
    stamps = [ln.time for ln in lines if ln.time is not None]
    return min(stamps) if stamps else None


def _min_id(lines: Sequence[LogLine]) -> int | None:
    """Return the lowest (oldest) record id in ``lines``, or None if untagged."""
    ids = [ln.id for ln in lines if ln.id is not None]
    return min(ids) if ids else None


def ahp_page_lines(
    family: str, firmware_version: tuple[int, int, int] | None
) -> int | None:
    """Return the ``&lines=`` page size to request, mirroring ``GetLogLines``.

    The app sends it only to AHP firmware 2.4 and newer; everything else
    gets no ``lines`` parameter and the charger's own page size.
    """
    if (
        family == "AHP"
        and firmware_version
        and firmware_version >= AHP_LINES_MIN_FIRMWARE
    ):
        return AHP_MAX_LOG_LINES
    return None


# --- "--since" specifications ------------------------------------------------------------

# Relative spans: "45m", "12h", "7d", "3w".
_SPAN_RE = re.compile(r"^(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>[mhdw])$", re.IGNORECASE)
_SPAN_UNITS = {
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
}
# Absolute forms accepted for --since, in the charger's or the user's terms.
_ABSOLUTE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M",
)

SINCE_HELP = (
    "today | yesterday | all | <N>m/h/d/w | YYYY-MM-DD[THH:MM[:SS]] | DD.MM.YYYY"
)


class SinceError(AlfenError, ValueError):
    """An unparseable ``--since`` specification."""


def parse_since(spec: str, *, now: datetime | None = None) -> datetime | None:
    """Turn a ``--since`` string into an aware UTC cutoff (None means "all").

    Bare dates and times are read in the *local* timezone -- the user's
    frame of reference -- and converted to UTC, which is what the charger
    stamps its lines with.
    """
    text = spec.strip()
    if not text:
        raise SinceError("empty --since value")
    local_now = (now or datetime.now(timezone.utc)).astimezone()
    # Naive local midnight; .astimezone() below reads a naive value as local
    # time, which gets the offset right even across a DST change.
    local_midnight = local_now.replace(
        tzinfo=None, hour=0, minute=0, second=0, microsecond=0
    )
    key = text.lower()
    if key in ("all", "everything", "0"):
        return None
    if key == "today":
        return local_midnight.astimezone(timezone.utc)
    if key == "yesterday":
        return (local_midnight - timedelta(days=1)).astimezone(timezone.utc)
    if m := _SPAN_RE.match(key):
        return local_now - float(m["n"]) * _SPAN_UNITS[m["unit"].lower()]
    for fmt in _ABSOLUTE_FORMATS:
        candidate = text.replace(" ", "T", 1) if "T" in fmt else text
        try:
            naive = datetime.strptime(candidate, fmt)
        except ValueError:
            continue
        return naive.astimezone(timezone.utc)
    try:  # last resort: whatever fromisoformat() takes, incl. an explicit offset
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise SinceError(
            f"unrecognised date/time {spec!r} (expected {SINCE_HELP})"
        ) from None
    return parsed.astimezone(timezone.utc)


def format_time(stamp: datetime | None) -> str:
    """Render a log timestamp in the local timezone, or "unknown"."""
    if stamp is None:
        return "unknown"
    return stamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def format_age(stamp: datetime | None, *, now: datetime | None = None) -> str:
    """Render how long ago ``stamp`` was, e.g. ``4h39m ago`` or ``2.5 days ago``."""
    if stamp is None:
        return ""
    seconds = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
    if seconds < 0:
        return "in the future"
    if seconds < SECONDS_PER_MINUTE:
        return "just now"
    if seconds < SECONDS_PER_HOUR:
        return f"{int(seconds // SECONDS_PER_MINUTE)}m ago"
    if seconds < SECONDS_PER_DAY:
        hours, rest = divmod(int(seconds), SECONDS_PER_HOUR)
        return f"{hours}h{rest // SECONDS_PER_MINUTE:02d}m ago"
    return f"{seconds / SECONDS_PER_DAY:.1f} days ago"


# --- Following the newest page ------------------------------------------------------------

# How often ``log --follow`` asks for the newest page.  The charger writes a
# line at a time, not a stream, so this is a poll; the app's own log view
# refreshes on the same order (PanelLog).
FOLLOW_INTERVAL_S = 2.0


@dataclass(frozen=True)
class Tail:
    """One poll of the newest log page."""

    lines: list[LogLine]  # only the lines not seen before, oldest first
    last_id: int | None  # the newest id now seen, to pass to the next poll
    missed: bool  # the whole page was new: lines in between were lost


def poll(
    source: _LogSource,
    last_id: int | None = None,
    *,
    lines_per_request: int | None = None,
) -> Tail:
    """Fetch the newest log page and return what is new since ``last_id``.

    The charger has no streaming endpoint, so following it means re-reading
    the newest page and dropping what we have already shown.  A page that is
    *entirely* new means the charger logged more than one page between polls
    and the lines in between are gone from our view -- ``missed`` says so
    rather than letting the gap pass silently.
    """
    page = parse_page(source.fetch_log(0, lines_per_request))
    if last_id is None:  # first poll: everything on the page is the backlog
        return Tail(lines=page, last_id=_max_id(page), missed=False)
    fresh = [ln for ln in page if ln.id is not None and ln.id > last_id]
    return Tail(
        lines=fresh,
        last_id=_max_id(fresh) or last_id,
        missed=bool(fresh) and len(fresh) == len(page),
    )


def _max_id(lines: Sequence[LogLine]) -> int | None:
    """Return the highest line id in ``lines``, or None if none carries one."""
    ids = [ln.id for ln in lines if ln.id is not None]
    return max(ids) if ids else None


# --- Paged download ----------------------------------------------------------------------


@dataclass
class Download:
    """The outcome of :func:`download`."""

    lines: list[LogLine]  # chronological (oldest page first), cutoff applied
    fetched: int = 0  # lines pulled off the charger, before the cutoff filter
    pages: int = 0
    dropped: int = 0  # fetched lines older than the cutoff (a partial last page)
    exhausted: bool = False  # the charger ran out of log: `oldest` is all it has
    truncated: bool = False  # we stopped at MAX_LOG_PAGES, not at the end
    oldest: datetime | None = None  # earliest timestamp actually fetched
    newest: datetime | None = None  # latest timestamp actually fetched
    seconds: float = 0.0


ProgressFn = Callable[[Download], None]


def download(
    source: _LogSource,
    since: datetime | None = None,
    *,
    lines_per_request: int | None = None,
    max_pages: int = MAX_LOG_PAGES,
    on_progress: ProgressFn | None = None,
) -> Download:
    """Page ``/api/log`` backwards until ``since`` is reached, then return it.

    ``since`` is an aware cutoff (None: fetch the whole buffer).  Paging
    stops once an *entire* page is older than it -- never on a single line,
    which a post-reboot clock jump could produce -- and the returned lines
    are then filtered to the cutoff exactly.  Pages are emitted
    oldest-first so the result reads chronologically, like the file the
    Windows app saves.

    ``on_progress`` is called after every page with the partially filled
    :class:`Download` (``lines`` is not yet populated).
    """
    started = time.monotonic()
    result = Download(lines=[])
    pages: list[list[LogLine]] = []
    seen: set[int] = set()
    offset = 0
    for _ in range(max_pages):
        page = parse_page(source.fetch_log(offset, lines=lines_per_request))
        if not page:
            result.exhausted = True
            break
        # A charger that ignores `offset` -- or one we have paged off the end
        # of -- repeats a page it already gave us; that is the end of the log.
        # Untagged lines can't be recognised as repeats, so a page has to
        # bring at least one *new record id* for us to ask for another.
        fresh = [ln for ln in page if ln.id is None or ln.id not in seen]
        new_ids = {ln.id for ln in fresh if ln.id is not None}
        if not new_ids:
            result.exhausted = True
            break
        seen |= new_ids
        pages.append(fresh)
        result.pages += 1
        result.fetched += len(fresh)
        page_newest, page_oldest = newest_time(fresh), oldest_time(fresh)
        if page_newest is not None:
            result.newest = (
                page_newest
                if result.newest is None
                else max(result.newest, page_newest)
            )
        if page_oldest is not None:
            result.oldest = (
                page_oldest
                if result.oldest is None
                else min(result.oldest, page_oldest)
            )
        result.seconds = time.monotonic() - started
        if on_progress is not None:
            on_progress(result)
        if since is not None and page_newest is not None and page_newest < since:
            break  # the whole page predates the cutoff: everything older will too
        offset += len(page)
    else:
        result.truncated = True
    # Oldest page first: within a page lines already run oldest-first, and each
    # further page steps further back, so reversing gives chronological order.
    ordered = [ln for page in reversed(pages) for ln in page]
    if since is None:
        result.lines = ordered
    else:
        result.lines = [ln for ln in ordered if ln.time is None or ln.time >= since]
        result.dropped = len(ordered) - len(result.lines)
    result.seconds = time.monotonic() - started
    return result


# --- Available range ---------------------------------------------------------------------


@dataclass
class LogRange:
    """How far back the charger's log buffer reaches (see :func:`probe_range`)."""

    oldest: datetime | None
    newest: datetime | None
    lines: int  # total lines held, to within one page
    page_lines: int  # the page size the charger served
    requests: int  # probes it took to find out
    exact: bool = True  # False: we hit the probe cap before finding the end


def probe_range(
    source: _LogSource,
    *,
    lines_per_request: int | None = None,
    max_pages: int = MAX_PROBE_PAGES,
    on_progress: Callable[[int, int], None] | None = None,
) -> LogRange | None:
    """Find the oldest log entry the charger still holds, without downloading it all.

    Nothing in the API reports this, so we search for it: ``offset`` counts
    lines back from the newest, and record ids decrease monotonically as it
    grows, so "page ``k`` is still inside the buffer" is a monotone
    predicate and can be bisected.  We double ``k`` until a page comes back
    empty (or repeats the deepest one we have -- what a charger that clamps
    ``offset`` does instead), then binary-search the last page that is
    still real.  That costs ~2*log2(pages) requests instead of one per page.

    Returns None when the log is empty.  ``on_progress(probe, offset)`` is
    called before each request.
    """
    requests = 0

    def fetch(page_index: int) -> list[LogLine]:
        nonlocal requests
        offset = page_index * page_lines
        if on_progress is not None:
            on_progress(requests, offset)
        requests += 1
        return parse_page(source.fetch_log(offset, lines=lines_per_request))

    page_lines = 1  # provisional, so the first fetch() asks for offset 0
    first = fetch(0)
    if not first:
        return None
    page_lines = len(first)
    newest = newest_time(first)
    # Invariant: page `lo` is real, page `hi` (once set) is past the end.
    lo, lo_min_id, lo_page = 0, _min_id(first), first
    hi: int | None = None
    step = 1
    while step <= max_pages:
        page = fetch(step)
        min_id = _min_id(page)
        if not page or lo_min_id is None or min_id is None or min_id >= lo_min_id:
            hi = step
            break
        lo, lo_min_id, lo_page = step, min_id, page
        step *= 2
    if hi is None:  # never found the end within the cap
        return LogRange(
            oldest=oldest_time(lo_page),
            newest=newest,
            lines=lo * page_lines + len(lo_page),
            page_lines=page_lines,
            requests=requests,
            exact=False,
        )
    while hi - lo > 1:  # bisect for the last page that is still inside the buffer
        mid = (lo + hi) // 2
        page = fetch(mid)
        min_id = _min_id(page)
        if not page or lo_min_id is None or min_id is None or min_id >= lo_min_id:
            hi = mid
        else:
            lo, lo_min_id, lo_page = mid, min_id, page
    return LogRange(
        oldest=oldest_time(lo_page),
        newest=newest,
        lines=lo * page_lines + len(lo_page),
        page_lines=page_lines,
        requests=requests,
    )


# --- Terminal progress -------------------------------------------------------------------


@dataclass
class DownloadProgress:
    """Draws the download's live stderr line (or logs it, in ``--debug``)."""

    since: datetime | None
    debug: bool = False
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _last_draw: float = field(default=0.0, init=False)

    def fraction(self, reached: datetime | None) -> float | None:
        """How much of the requested span is covered, or None when unbounded."""
        if self.since is None or reached is None:
            return None
        span = (self.now - self.since).total_seconds()
        if span <= 0:
            return 1.0
        return max(0.0, min(1.0, (self.now - reached).total_seconds() / span))

    def __call__(self, state: Download, *, final: bool = False) -> None:
        """Redraw (or log) the line for one just-fetched page."""
        reached = state.oldest
        frac = 1.0 if final else self.fraction(reached)
        back = f"back to {format_time(reached)}" if reached else "reading"
        if self.debug:
            if not final:
                print(
                    f"[debug] -- log page {state.pages}: {state.fetched} lines, {back}",
                    file=sys.stderr,
                )
            return
        now = time.monotonic()
        if not final and now - self._last_draw < PROGRESS_MIN_INTERVAL_S:
            return  # throttle mid-download redraws, but always draw the last one
        self._last_draw = now
        shown = f"[{bar(frac)}] {frac:4.0%}  " if frac is not None else ""
        write_live(
            f"  Downloading log  {shown}{state.fetched} lines  {back}  "
            f"elapsed {fmt_duration(state.seconds)}"
        )

    def finish(self, state: Download | None = None) -> None:
        """Draw the completed line and close it (a no-op in debug mode)."""
        if self.debug:
            return
        if state is not None and state.fetched:
            self(state, final=True)
        end_live()
