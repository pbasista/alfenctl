"""The charger's transaction database: charging sessions and OCPP events.

``GET /api/transactions?offset=N`` returns a page of the charger's
transaction log -- the record of what it charged, for whom, and what it
still owes its backoffice.  Paging runs *backwards*: the app starts at
``offset=0xFFFFFFFF`` ("give me the newest") and then asks again with the
offset of the last record it got, until a page adds nothing new
(``ICUTransactions.Read``).

Records are ``<offset>_<text>`` lines whose text is one of several
prefixed forms, all of which this module parses (``ICUTransactionItem``):

===========  ============================================================
``tx:``      a complete session: start and stop in one record
``txstart:`` / ``txstop:``  the OCPP 2.0 split form, paired by id here
``mv:``      a periodic meter value inside a session
``sn:``      a status notification (socket state change)
``rs:`` / ``rss:``  a reservation and its outcome
``se:``      a security event (firmware update, tamper, time set, ...)
``dto:``     a date/time offset correction
===========  ============================================================

A trailing ``Y``/``N`` on most records is the charger's "still to send to
the backoffice" flag, which is why the database exists at all.

The raw text of every record is kept verbatim: the app's own CSV export is
just those lines, and the firmware has more variants than either of us has
seen.  Anything unrecognised still comes out, tagged ``unknown``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterable, Protocol, Sequence

from devicectl.progress import SECONDS_PER_HOUR

# Where the app starts paging: "the newest record" (ICUTransactions.Read).
NEWEST_OFFSET = 0xFFFFFFFF
# Hard cap on pages, so a charger that ignores `offset` can't spin us.
MAX_PAGES = 2000
# The charger says this when there is nothing to report.
EMPTY_MARKER = "empty transaction database"


# ICUTransactionStopReason
STOP_REASONS = {
    0: "other",
    1: "local",
    2: "emergency-stop",
    3: "ev-disconnected",
    4: "hard-reset",
    5: "power-loss",
    6: "reboot",
    7: "remote",
    8: "soft-reset",
    9: "unlock-command",
    10: "deauthorized",
    255: "none",
}
# ICUTransactionTriggerReason
TRIGGER_REASONS = {
    0: "authorized",
    1: "cable-plugged-in",
    2: "charging-rate-changed",
    3: "charging-state-changed",
    4: "deauthorized",
    5: "energy-limit-reached",
    6: "ev-communication-lost",
    7: "ev-connect-timeout",
    8: "meter-value-clock",
    9: "meter-value-periodic",
    10: "time-limit-reached",
    11: "trigger",
    12: "unlock-command",
    13: "stop-authorized",
    14: "ev-departed",
    15: "ev-detected",
    16: "remote-stop",
    17: "remote-start",
    18: "abnormal-condition",
    19: "signed-data-received",
    20: "reset-command",
    31: "none",
}
# ICUTransactionChargingState
CHARGING_STATES = {
    0: "none",
    1: "charging",
    2: "ev-connected",
    3: "suspended-ev",
    4: "suspended-evse",
    5: "idle",
}
# ICUTransactionSecurityEvent
SECURITY_EVENTS = {
    0: "none",
    1: "firmware-updated",
    2: "authentication-failed-at-csms",
    3: "csms-failed-to-authenticate",
    4: "set-system-time",
    5: "start-up-device",
    6: "reset-or-reboot",
    7: "security-log-cleared",
    8: "reconfig-of-parameter",
    9: "memory-exhaustion",
    10: "invalid-messages",
    11: "replay-attack",
    12: "tamper-detection",
    13: "firmware-signature",
    14: "firmware-sign-certificate",
    15: "csms-certificate",
    16: "cp-certificate",
    17: "tls-version",
    18: "tls-cipher-suite",
}
# ICUTransactionReservationStatus
RESERVATION_STATUSES = {-1: "unknown", 0: "expired", 1: "removed"}

# Field counts of the record grammar.  A tx record is comma-separated
# (``id``, ``socket``, start half[, stop half]); each half is
# space-separated ``<date> <time> <meter>kWh <tag> [reasons] <Y|N>``, and
# which reasons appear tells the generations apart.
_TX_FIELDS_MIN = 3  # id, socket, start
_TX_FIELDS_WITH_STOP = 4  # ... and a stop half
_HALF_MIN = 5  # date time meter tag to-send
_HALF_WITH_STOP_REASON = 6  # ... stop-reason to-send
_HALF_WITH_OCPP2 = 7  # ... trigger charging-state to-send
_MV_MIN = 6  # mv: socket, date, time, meter, kind, to-send
_SN_MIN = 8  # sn: the shortest status notification
_SN_WITH_OCPP2 = 10  # ... plus trigger and charging state
_RS_MIN = 9  # rs: #id ... tag ... socket, ... date time
_RSS_MIN = 3  # rss: id status (to-send)
_SE_MIN = 4  # se: date time: event (to-send)

_TIMESTAMP = "%Y-%m-%d %H:%M:%S"
_TIMESTAMP_LEN = 19  # "yyyy-MM-dd HH:mm:ss", the width the app slices

# The app strips these before splitting a page into records: the JSON
# envelope the newer firmware wraps the text in, an "AP;<...>; " prefix on
# some lines, and a literal "(null) ".
_ENVELOPE_RE = re.compile(r'\{"version":\d+,')
_AP_PREFIX_RE = re.compile(r"AP;.*?; ")
_NULL_RE = re.compile(r"\(\s*null\s*\) ")

# "id = 0A1B" (hex) and "socket1" inside a record's head.
_ID_RE = re.compile(r"id\D*([0-9A-Fa-f]+)")
_SOCKET_RE = re.compile(r"socket\D*(\d+)")


class _Source(Protocol):
    """The one charger call this module needs."""

    def fetch_transactions(self, offset: int = NEWEST_OFFSET) -> str: ...


# --- Records -----------------------------------------------------------------------------


@dataclass
class Record:
    """One row of the transaction database.

    Every field beyond ``offset``/``kind``/``raw`` is best-effort: the
    firmware emits several generations of each record shape, so a field the
    charger did not print stays None rather than being invented.
    """

    offset: int
    kind: str  # transaction | start | stop | meter-value | status | ... | unknown
    raw: str
    transaction_id: int | None = None
    socket: int | None = None
    start_time: datetime | None = None
    stop_time: datetime | None = None
    start_meter_kwh: float | None = None
    stop_meter_kwh: float | None = None
    start_tag: str | None = None
    stop_tag: str | None = None
    stop_reason: str | None = None
    trigger_reason: str | None = None
    charging_state: str | None = None
    security_event: str | None = None
    reservation_status: str | None = None
    start_to_send: bool | None = None
    stop_to_send: bool | None = None
    extra: str = ""

    @property
    def time(self) -> datetime | None:
        """When the record happened: its start, or its stop if it has no start."""
        return self.start_time or self.stop_time

    @property
    def energy_kwh(self) -> float | None:
        """Energy delivered, when the record carries both meter readings."""
        if self.start_meter_kwh is None or self.stop_meter_kwh is None:
            return None
        return round(self.stop_meter_kwh - self.start_meter_kwh, 3)

    @property
    def duration(self) -> timedelta | None:
        """How long the session ran, when the record carries both times."""
        if self.start_time is None or self.stop_time is None:
            return None
        return self.stop_time - self.start_time


def _timestamp(text: str) -> datetime | None:
    """Parse the leading ``yyyy-MM-dd HH:mm:ss`` of ``text`` (charger local time)."""
    try:
        return datetime.strptime(text[:_TIMESTAMP_LEN], _TIMESTAMP)
    except ValueError:
        return None


def _meter(text: str) -> float | None:
    """Parse a ``1234.5kWh`` meter reading."""
    try:
        return float(text.strip().rstrip("kWh ").strip())
    except ValueError:
        return None


def _tag(text: str) -> str | None:
    """Normalise an RFID tag field; the charger prints ``(null)`` for none."""
    value = text.strip()
    return None if value in ("", "(null)", "null") else value


def _flag(text: str) -> bool:
    """Parse the trailing "still to send to the backoffice" flag."""
    return text.strip() == "Y"


def _enum(values: dict[int, str], text: str) -> str | None:
    """Look up an integer enum field, keeping the raw number when unknown."""
    try:
        code = int(text.strip().strip(",()"))
    except ValueError:
        return None
    return values.get(code, str(code))


def _head(record: Record, head: str) -> None:
    """Fill in the ``id = <hex>, socket<n>`` head shared by the tx forms."""
    if m := _ID_RE.search(head):
        record.transaction_id = int(m[1], 16)
    if m := _SOCKET_RE.search(head):
        record.socket = int(m[1])


def _start_fields(record: Record, text: str) -> None:
    """Parse ``<time> <meter>kWh <tag> [reasons] <Y|N>`` as the session start."""
    parts = text.split()
    if len(parts) < _HALF_MIN:
        return
    record.start_time = _timestamp(text)
    record.start_meter_kwh = _meter(parts[2])
    record.start_tag = _tag(parts[3])
    record.start_to_send = _flag(parts[-1])
    if len(parts) == _HALF_WITH_STOP_REASON:  # txstart: ..., <stop reason>, <to send>
        record.stop_reason = _enum(STOP_REASONS, parts[4])
    elif len(parts) >= _HALF_WITH_OCPP2:  # txstart2: ..., <trigger>, <state>, <to send>
        record.trigger_reason = _enum(TRIGGER_REASONS, parts[4])
        record.charging_state = _enum(CHARGING_STATES, parts[5])


def _stop_fields(record: Record, text: str) -> None:
    """Parse ``<time> <meter>kWh <tag> [reasons] <Y|N>`` as the session stop."""
    parts = text.split()
    if len(parts) < _HALF_MIN:
        return
    record.stop_time = _timestamp(text)
    record.stop_meter_kwh = _meter(parts[2])
    record.stop_tag = _tag(parts[3])
    record.stop_to_send = _flag(parts[-1])
    if len(parts) == _HALF_WITH_STOP_REASON:  # tx: the stop half carries a reason
        record.stop_reason = _enum(STOP_REASONS, parts[4])
    elif len(parts) >= _HALF_WITH_OCPP2:  # txstop2: <trigger>, <state>, <to send>
        record.trigger_reason = _enum(TRIGGER_REASONS, parts[4])
        record.charging_state = _enum(CHARGING_STATES, parts[5])


def _body(text: str) -> str:
    """Return what follows a record's ``<prefix>:``."""
    return text.split(":", 1)[1].strip() if ":" in text else ""


# --- one parser per record kind ------------------------------------------------------------
# Every line in the database is ``<offset>_<prefix>: <body>``, and the prefix
# says both what kind of thing happened and how the body is laid out.  Each
# shape gets a function of its own below and an entry in :data:`PARSERS`; a
# prefix nobody has seen leaves the record ``unknown`` with its text intact,
# which is what the CLI prints for it.
#
# Each parser is handed a record that already knows its offset, kind and raw
# text, and fills in what it can.  A body too short for its shape is a record
# that stays half-filled rather than one that is thrown away: a truncated
# line still says a session happened.


def _parse_tx(record: Record, body: str) -> None:
    """``tx``: a whole session, start half and stop half in one line."""
    fields = [f.strip() for f in body.split(",")]
    if len(fields) < _TX_FIELDS_MIN:
        return
    _head(record, f"{fields[0]},{fields[1]}")
    _start_fields(record, fields[2])
    if len(fields) >= _TX_FIELDS_WITH_STOP:
        _stop_fields(record, fields[3])


def _parse_txstart(record: Record, body: str) -> None:
    """``txstart``/``txstart2``: the start half on its own."""
    fields = [f.strip() for f in body.split(",")]
    if len(fields) < _TX_FIELDS_MIN:
        return
    _head(record, f"{fields[0]},{fields[1]}")
    _start_fields(record, fields[2])


def _parse_txstop(record: Record, body: str) -> None:
    """``txstop``/``txstop2``: the stop half on its own."""
    fields = [f.strip() for f in body.split(",")]
    if len(fields) < _TX_FIELDS_MIN:
        return
    _head(record, f"{fields[0]},{fields[1]}")
    _stop_fields(record, fields[2])


def _socket_of(text: str) -> int | None:
    """Read a ``socket1,``-style field as a number, or None."""
    digits = text.strip(",")
    return int(digits) if digits.isdigit() else None


def _parse_meter_value(record: Record, body: str) -> None:
    """``mv``: one meter reading, and whether it has reached the backoffice."""
    parts = body.split()
    if len(parts) < _MV_MIN:
        return
    record.socket = _socket_of(parts[1])
    record.start_time = _timestamp(f"{parts[2]} {parts[3]}")
    record.start_meter_kwh = _meter(parts[4])
    record.start_to_send = _flag(parts[-1])
    if parts[-2].lower() in ("start", "stop", "regular"):
        record.extra = parts[-2].lower()


def _parse_status(record: Record, body: str) -> None:
    """``sn``/``sn3``: a status notification, with a free-text middle."""
    parts = body.split()
    if parts and parts[0] == ":":  # some firmware doubles the separator
        parts = parts[1:]
    if len(parts) < _SN_MIN:
        return
    record.socket = _socket_of(parts[1])
    record.start_time = _timestamp(f"{parts[2]} {parts[3]}")
    # Whatever sits between the timestamp and the three trailing OCPP fields
    # is the notification's own words, and there is no telling how many.
    middle = " ".join(p.strip(",") for p in parts[6:-3])
    record.extra = " ".join(
        x for x in (parts[4].strip(","), parts[5].strip(","), middle) if x
    ).strip()
    if len(parts) >= _SN_WITH_OCPP2:
        record.trigger_reason = _enum(TRIGGER_REASONS, parts[-3])
        record.charging_state = _enum(CHARGING_STATES, parts[-2])


def _parse_reservation(record: Record, body: str) -> None:
    """``rs``: a reservation made against a socket."""
    parts = body.split()
    if len(parts) < _RS_MIN:
        return
    if parts[0].startswith("#") and parts[0][1:].isdigit():
        record.transaction_id = int(parts[0][1:])
    record.start_tag = _tag(parts[2])
    record.socket = _socket_of(parts[5])
    record.start_time = _timestamp(f"{parts[7]} {parts[8]}")


def _parse_reservation_status(record: Record, body: str) -> None:
    """``rss``: what became of a reservation."""
    parts = body.split()
    if len(parts) < _RSS_MIN:
        return
    ident = parts[0].strip(" :")
    if ident.isdigit():
        record.transaction_id = int(ident)
    record.reservation_status = _enum(RESERVATION_STATUSES, parts[1])
    record.start_to_send = _flag(parts[2].strip("()"))


def _parse_security_event(record: Record, body: str) -> None:
    """``se``: a security event, in the OCPP 1.6 security profile's sense."""
    parts = body.split()
    if len(parts) < _SE_MIN:
        return
    record.start_time = _timestamp(f"{parts[0]} {parts[1].strip(': ')}")
    record.security_event = _enum(SECURITY_EVENTS, parts[2])
    record.start_to_send = _flag(parts[3].strip("()"))


def _parse_clock_offset(record: Record, body: str) -> None:
    """``dto``: the charger's clock jumped, by this many seconds."""
    try:
        record.extra = str(timedelta(seconds=int(body)))
    except ValueError:
        record.extra = body


PARSERS: dict[str, tuple[str, Callable[[Record, str], None]]] = {
    "tx": ("transaction", _parse_tx),
    "txstart": ("start", _parse_txstart),
    "txstart2": ("start", _parse_txstart),
    "txstop": ("stop", _parse_txstop),
    "txstop2": ("stop", _parse_txstop),
    "mv": ("meter-value", _parse_meter_value),
    "sn": ("status", _parse_status),
    "sn3": ("status", _parse_status),
    "rs": ("reservation", _parse_reservation),
    "rss": ("reservation-status", _parse_reservation_status),
    "se": ("security-event", _parse_security_event),
    "dto": ("clock-offset", _parse_clock_offset),
}


def parse_record(line: str) -> Record | None:
    """Parse one ``<offset>_<text>`` line; return None for a blank one."""
    stripped = line.strip()
    if not stripped or "_" not in stripped:
        return None
    head, _, text = stripped.partition("_")
    try:
        offset = int(head)
    except ValueError:
        return None
    text = text.strip()
    record = Record(offset=offset, kind="unknown", raw=text)
    known = PARSERS.get(text.split(":", 1)[0])
    if known is not None:
        record.kind, parse = known
        parse(record, _body(text))
    return record


def parse_page(page: str) -> list[Record]:
    """Parse one ``/api/transactions`` body into records.

    The scrubbing is the app's ``unwrapTransActions``: drop the JSON
    envelope the newer firmware adds, an ``AP;...; `` prefix, a literal
    ``(null) ``, and the stray closing brace, then split on newlines.
    """
    text = _ENVELOPE_RE.sub("", page)
    text = _AP_PREFIX_RE.sub("", text)
    text = _NULL_RE.sub("", text)
    text = text.replace("}", "")
    return [r for r in map(parse_record, text.splitlines()) if r is not None]


# --- Paged download ----------------------------------------------------------------------


@dataclass
class Download:
    """The outcome of :func:`download`."""

    records: list[Record] = field(default_factory=list)
    pages: int = 0
    empty: bool = False  # the charger reported an empty transaction database
    truncated: bool = False  # stopped at MAX_PAGES, not at the end


def download(
    source: _Source,
    *,
    max_pages: int = MAX_PAGES,
    on_progress: Callable[[Download], None] | None = None,
) -> Download:
    """Read the whole transaction database, newest page first.

    Mirrors ``ICUTransactions.Read``: start at :data:`NEWEST_OFFSET`, then
    ask again with the offset of the last record the page brought, until a
    page brings nothing new.  Records come back oldest-first.
    """
    result = Download()
    seen: set[int] = set()
    offset = NEWEST_OFFSET
    for _ in range(max_pages):
        page = source.fetch_transactions(offset)
        if EMPTY_MARKER in page.lower():
            result.empty = not result.records
            break
        records = parse_page(page)
        fresh = [r for r in records if r.offset not in seen]
        if not fresh:
            break
        seen.update(r.offset for r in fresh)
        result.records.extend(fresh)
        result.pages += 1
        offset = fresh[-1].offset
        if on_progress is not None:
            on_progress(result)
    else:
        result.truncated = True
    result.records.sort(key=lambda r: (r.time or datetime.min, r.offset))
    return result


# --- Sessions ----------------------------------------------------------------------------


@dataclass
class Session:
    """A charging session: one ``tx:`` record, or a paired ``txstart``/``txstop``."""

    transaction_id: int | None
    socket: int | None
    start_time: datetime | None
    stop_time: datetime | None
    start_meter_kwh: float | None
    stop_meter_kwh: float | None
    start_tag: str | None
    stop_tag: str | None
    stop_reason: str | None = None
    complete: bool = False  # False: still running, or its stop record is gone

    @property
    def energy_kwh(self) -> float | None:
        """Energy delivered over the session."""
        if self.start_meter_kwh is None or self.stop_meter_kwh is None:
            return None
        return round(self.stop_meter_kwh - self.start_meter_kwh, 3)

    @property
    def duration(self) -> timedelta | None:
        """How long the session ran."""
        if self.start_time is None or self.stop_time is None:
            return None
        return self.stop_time - self.start_time

    @property
    def average_kw(self) -> float | None:
        """Mean power over the session, when both ends are known."""
        energy, duration = self.energy_kwh, self.duration
        if energy is None or duration is None or duration.total_seconds() <= 0:
            return None
        return round(energy / (duration.total_seconds() / SECONDS_PER_HOUR), 2)


def sessions(records: Iterable[Record]) -> list[Session]:
    """Fold records into charging sessions.

    A ``tx:`` record is already a whole session.  The OCPP 2.0 firmware
    splits it into ``txstart:``/``txstop:`` instead, which are matched here
    by transaction id; a start with no stop is a session that was still
    running (or whose stop has been overwritten), and comes back
    ``complete=False``.
    """
    out: list[Session] = []
    open_starts: dict[int | None, Session] = {}
    for record in records:
        if record.kind == "transaction":
            out.append(
                Session(
                    transaction_id=record.transaction_id,
                    socket=record.socket,
                    start_time=record.start_time,
                    stop_time=record.stop_time,
                    start_meter_kwh=record.start_meter_kwh,
                    stop_meter_kwh=record.stop_meter_kwh,
                    start_tag=record.start_tag,
                    stop_tag=record.stop_tag,
                    stop_reason=record.stop_reason,
                    complete=record.stop_time is not None,
                )
            )
        elif record.kind == "start":
            session = Session(
                transaction_id=record.transaction_id,
                socket=record.socket,
                start_time=record.start_time,
                stop_time=None,
                start_meter_kwh=record.start_meter_kwh,
                stop_meter_kwh=None,
                start_tag=record.start_tag,
                stop_tag=None,
            )
            open_starts[record.transaction_id] = session
            out.append(session)
        elif record.kind == "stop":
            session = open_starts.pop(record.transaction_id, None)
            if session is None:  # a stop whose start has rolled out of the buffer
                session = Session(
                    transaction_id=record.transaction_id,
                    socket=record.socket,
                    start_time=None,
                    stop_time=None,
                    start_meter_kwh=None,
                    stop_meter_kwh=None,
                    start_tag=None,
                    stop_tag=None,
                )
                out.append(session)
            session.stop_time = record.stop_time
            session.stop_meter_kwh = record.stop_meter_kwh
            session.stop_tag = record.stop_tag
            session.stop_reason = record.stop_reason
            session.complete = record.stop_time is not None
    return out


# --- Output ------------------------------------------------------------------------------

# Columns of the session CSV, in order.
SESSION_COLUMNS = (
    "transaction_id",
    "socket",
    "start_time",
    "stop_time",
    "duration",
    "start_kwh",
    "stop_kwh",
    "energy_kwh",
    "average_kw",
    "start_tag",
    "stop_tag",
    "stop_reason",
    "complete",
)


def _csv_time(stamp: datetime | None) -> str:
    """Render a record timestamp for CSV, or empty."""
    return stamp.strftime(_TIMESTAMP) if stamp else ""


def _csv_duration(span: timedelta | None) -> str:
    """Render a duration as ``H:MM:SS``, or empty."""
    if span is None:
        return ""
    total = int(span.total_seconds())
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def session_row(session: Session) -> list[str]:
    """Return one :data:`SESSION_COLUMNS` row for ``session``."""
    return [
        f"{session.transaction_id:X}" if session.transaction_id is not None else "",
        str(session.socket) if session.socket is not None else "",
        _csv_time(session.start_time),
        _csv_time(session.stop_time),
        _csv_duration(session.duration),
        f"{session.start_meter_kwh:.3f}" if session.start_meter_kwh is not None else "",
        f"{session.stop_meter_kwh:.3f}" if session.stop_meter_kwh is not None else "",
        f"{session.energy_kwh:.3f}" if session.energy_kwh is not None else "",
        f"{session.average_kw:.2f}" if session.average_kw is not None else "",
        session.start_tag or "",
        session.stop_tag or "",
        session.stop_reason or "",
        "yes" if session.complete else "no",
    ]


def record_dict(record: Record) -> dict[str, object]:
    """Return ``record`` as a JSON-ready dict, dropping fields the charger omitted."""
    out: dict[str, object] = {"offset": record.offset, "kind": record.kind}
    for name in (
        "transaction_id",
        "socket",
        "start_time",
        "stop_time",
        "start_meter_kwh",
        "stop_meter_kwh",
        "start_tag",
        "stop_tag",
        "stop_reason",
        "trigger_reason",
        "charging_state",
        "security_event",
        "reservation_status",
        "start_to_send",
        "stop_to_send",
    ):
        value = getattr(record, name)
        if value is not None:
            out[name] = value.isoformat() if isinstance(value, datetime) else value
    if record.energy_kwh is not None:
        out["energy_kwh"] = record.energy_kwh
    if record.extra:
        out["extra"] = record.extra
    out["raw"] = record.raw
    return out


def since_cutoff(records: Sequence[Record], since: datetime | None) -> list[Record]:
    """Keep records at or after ``since`` (naive charger local time)."""
    if since is None:
        return list(records)
    limit = since.astimezone().replace(tzinfo=None) if since.tzinfo else since
    return [r for r in records if r.time is None or r.time >= limit]


# --- Summaries ---------------------------------------------------------------------------
# Everything here is arithmetic over sessions already downloaded: no extra
# request, and nothing the charger itself can answer.  It is the question a
# charge log is usually opened to answer -- how much, over what period, by
# whom -- which otherwise means exporting the CSV and opening a spreadsheet.


@dataclass
class Totals:
    """One row of a summary: how many sessions, how much energy, how long."""

    key: str
    sessions: int = 0
    energy_kwh: float = 0.0
    duration: timedelta = field(default_factory=timedelta)
    first: datetime | None = None
    last: datetime | None = None
    incomplete: int = 0
    """Sessions whose energy could not be counted, because an end is missing."""

    @property
    def average_kwh(self) -> float | None:
        """Mean energy per session that could be counted."""
        counted = self.sessions - self.incomplete
        return round(self.energy_kwh / counted, 3) if counted else None


def _add(row: Totals, session: Session) -> None:
    """Fold one session into a running total."""
    row.sessions += 1
    energy = session.energy_kwh
    if energy is None:
        row.incomplete += 1
    else:
        row.energy_kwh = round(row.energy_kwh + energy, 3)
    span = session.duration
    if span is not None:
        row.duration += span
    stamp = session.start_time
    if stamp is not None:
        row.first = stamp if row.first is None else min(row.first, stamp)
        row.last = stamp if row.last is None else max(row.last, stamp)


UNKNOWN_GROUP = "(unknown)"


def summarise(
    rows: Iterable[Session], key: Callable[[Session], str | None]
) -> list[Totals]:
    """Group sessions by ``key`` and total each group.

    A session the key cannot place -- no socket, no tag, no start time --
    goes under ``"(unknown)"`` rather than being dropped: a summary that
    silently loses energy is worse than one with an untidy row in it.
    """
    out: dict[str, Totals] = {}
    for session in rows:
        name = key(session) or UNKNOWN_GROUP
        _add(out.setdefault(name, Totals(key=name)), session)
    return [out[name] for name in sorted(out)]


def by_day(session: Session) -> str | None:
    """Group key: the calendar day a session started on."""
    return (
        None if session.start_time is None else session.start_time.strftime("%Y-%m-%d")
    )


def by_month(session: Session) -> str | None:
    """Group key: the calendar month a session started in."""
    return None if session.start_time is None else session.start_time.strftime("%Y-%m")


def by_socket(session: Session) -> str | None:
    """Group key: which socket delivered the session."""
    return None if session.socket is None else f"socket {session.socket}"


def by_tag(session: Session) -> str | None:
    """Group key: the tag that started the session."""
    return session.start_tag or session.stop_tag


GROUPINGS: dict[str, Callable[[Session], str | None]] = {
    "day": by_day,
    "month": by_month,
    "socket": by_socket,
    "tag": by_tag,
}


def total(rows: Iterable[Session]) -> Totals:
    """Total every session as one row."""
    everything = Totals(key="total")
    for session in rows:
        _add(everything, session)
    return everything
