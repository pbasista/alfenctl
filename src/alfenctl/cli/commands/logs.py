"""``alfenctl log`` and ``alfenctl transactions`` -- what the charger recorded.

Both read a paged history off the charger and both can take a while, so
both report progress; the log can also be followed live.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from devicectl.cli.command import Command
from devicectl.progress import bar, end_live, fmt_duration, write_live

from alfenctl import transactions
from alfenctl.charger import AlfenCharger, ChargerInfo
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import confirm, print_table, write_out
from alfenctl.logs import (
    FOLLOW_INTERVAL_S,
    LOG_TYPES,
    MAX_LOG_PAGES,
    PROGRESS_MIN_INTERVAL_S,
    SINCE_HELP,
    Download,
    LogLine,
    ahp_page_lines,
    download,
    format_age,
    format_time,
    parse_since,
    poll,
    probe_range,
)

# --- the download's live line --------------------------------------------------------------
# :func:`alfenctl.logs.download` says how it is getting on by calling whatever
# it was handed after every page, and never prints: the browser turns the same
# calls into job progress.  Drawing them is a terminal's business, so it is
# done here rather than there.


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


def _log_page_lines(charger: AlfenCharger) -> tuple[str, int | None]:
    """Return ``(object id, &lines= page size)`` for a log read.

    The page size is the app's: AHP >= 2.4 gets an explicit one, every other
    firmware lets the charger choose.  One ``basic_info()`` covers both the
    default output filename and that decision.
    """
    info = charger.basic_info()
    return info.object_id or "charger", ahp_page_lines(
        info.family, info.firmware_version
    )


def cmd_log_range(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Report how far back the charger's log buffer reaches (``log --range``)."""
    object_id, page_lines = _log_page_lines(charger)

    def tick(probe: int, offset: int) -> None:
        if args.debug:
            print(f"[debug] -- probing log offset {offset}", file=sys.stderr)
        else:
            write_live(f"  Probing the log buffer  ({probe + 1} requests)")

    span = probe_range(charger, lines_per_request=page_lines, on_progress=tick)
    if not args.debug:
        end_live()
    if span is None:
        print("The charger log is empty.", file=sys.stderr)
        return EXIT_OK
    about = "" if span.exact else "at least "
    print(f"Log buffer on {object_id}:")
    print(f"  oldest entry : {format_time(span.oldest)}  ({format_age(span.oldest)})")
    print(f"  newest entry : {format_time(span.newest)}  ({format_age(span.newest)})")
    print(f"  lines        : {about}{span.lines} (in pages of {span.page_lines})")
    print(f"  found in     : {span.requests} requests")
    if span.oldest is not None:
        print(
            f"\nExport all of it with: alfenctl log --since {span.oldest.astimezone():%Y-%m-%d}"
        )
    print(
        "\nNote: the charger boots with its clock at the firmware build date "
        "until\nNTP or the app sets it, so timestamps can jump backwards "
        "around a restart."
    )
    return EXIT_OK


# How many recent lines `log --follow` shows before it starts streaming.
FOLLOW_BACKLOG_LINES = 10


def _keep_kind(line: LogLine, kinds: set[str] | None) -> bool:
    """Whether a log line passes the --type filter (unkinded lines never do)."""
    return kinds is None or (line.kind or "") in kinds


def cmd_log_follow(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Print new log lines as the charger writes them (``log --follow``)."""
    import time

    object_id, page_lines = _log_page_lines(charger)
    kinds = set(args.type) if args.type else None
    backlog = args.tail if args.tail is not None else FOLLOW_BACKLOG_LINES
    print(
        f"Following {object_id}'s log; press Ctrl+C to stop.",
        file=sys.stderr,
    )
    state = poll(charger, None, lines_per_request=page_lines)
    for line in [ln for ln in state.lines if _keep_kind(ln, kinds)][-backlog:]:
        print(line.text, flush=True)
    while True:
        time.sleep(args.interval)
        state = poll(charger, state.last_id, lines_per_request=page_lines)
        if state.missed:
            print(
                "  ... the charger logged faster than we could read; "
                "some lines were skipped",
                file=sys.stderr,
            )
        for line in state.lines:
            if _keep_kind(line, kinds):
                print(line.text, flush=True)


def cmd_log(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Export the charger's own event log since a date (GET /api/log, paged)."""
    if args.range:
        return cmd_log_range(charger, args)
    if args.follow:
        return cmd_log_follow(charger, args)
    since = None if args.all else parse_since(args.since)
    object_id, page_lines = _log_page_lines(charger)
    progress = DownloadProgress(since, debug=args.debug)
    result = download(
        charger, since, lines_per_request=page_lines, on_progress=progress
    )
    progress.finish(result)
    _report_download(result, since)

    kinds = set(args.type) if args.type else None
    lines = [ln.text for ln in result.lines if _keep_kind(ln, kinds)]
    if args.tail:
        lines = lines[-args.tail :]
    if args.grep:
        pat = re.compile(str(args.grep), re.IGNORECASE)
        lines = [ln for ln in lines if pat.search(ln)]
    if not lines:
        if not result.fetched:
            print("The charger log is empty.", file=sys.stderr)
        else:
            print("No log lines in the requested period.", file=sys.stderr)
        return EXIT_OK
    # Named file by default on a terminal, like export: the charger's object
    # id keeps one log per device distinguishable.
    return write_out(
        "\n".join(lines) + "\n",
        getattr(args, "file", None),
        default_name=f"{object_id}.log",
        yes=args.yes,
        summary=f"{len(lines)} log lines",
    )


def _report_download(result: Download, since: datetime | None) -> None:
    """Summarise what came off the charger, and why the download stopped."""
    if not result.fetched:
        return
    covered = (
        f"{format_time(result.oldest)} .. {format_time(result.newest)}"
        if result.oldest and result.newest
        else "unknown range"
    )
    print(
        f"Downloaded {result.fetched} lines in {result.pages} pages "
        f"({covered}) in {result.seconds:.1f}s",
        file=sys.stderr,
    )
    if result.truncated:
        print(
            f"warning: stopped at the {MAX_LOG_PAGES}-page cap; the log may go "
            "back further",
            file=sys.stderr,
        )
    elif (
        result.exhausted
        and since is not None
        and result.oldest
        and result.oldest > since
    ):
        print(
            f"note: the charger only keeps its log back to "
            f"{format_time(result.oldest)}, later than the requested "
            f"{format_time(since)}",
            file=sys.stderr,
        )
    if result.dropped:
        print(
            f"note: dropped {result.dropped} fetched lines older than the cutoff "
            "(the charger pages the log in fixed-size blocks)",
            file=sys.stderr,
        )


def _download_transactions(
    charger: AlfenCharger, args: argparse.Namespace
) -> transactions.Download:
    """Read the whole transaction database, saying how it is getting on."""

    def tick(state: transactions.Download) -> None:
        if args.debug:
            print(
                f"[debug] -- transactions page {state.pages}: "
                f"{len(state.records)} records",
                file=sys.stderr,
            )
        else:
            write_live(
                f"  Reading transactions  {len(state.records)} records  "
                f"({state.pages} pages)"
            )

    result = transactions.download(charger, on_progress=tick)
    if not args.debug:
        end_live()
    if result.truncated:
        print(
            f"warning: stopped at the {transactions.MAX_PAGES}-page cap",
            file=sys.stderr,
        )
    return result


def _sessions_for(records: list, args: argparse.Namespace) -> list:
    """Pair the records into sessions, keeping the socket that was asked for."""
    rows = transactions.sessions(records)
    if args.socket is not None:
        rows = [s for s in rows if s.socket == args.socket]
    return rows


def _transactions_payload(records: list, args: argparse.Namespace) -> tuple[str, str]:
    """Render the records in the asked-for format, with the suffix to save it under."""
    import csv
    import io

    if args.raw:
        return "\n".join(f"{r.offset}_{r.raw}" for r in records) + "\n", "txt"
    if args.json:
        doc = [transactions.record_dict(r) for r in records]
        return json.dumps(doc, indent=2) + "\n", "json"
    rows = _sessions_for(records, args)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(transactions.SESSION_COLUMNS)
    writer.writerows(transactions.session_row(s) for s in rows)
    print(f"{len(rows)} charging session(s).", file=sys.stderr)
    return buf.getvalue(), "csv"


def cmd_transactions(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Export the charger's transaction database (charging sessions and events)."""
    since = None if args.all else parse_since(args.since)
    info = charger.basic_info()
    if args.erase:
        return _erase_transactions(charger, info, args)

    result = _download_transactions(charger, args)
    if result.empty or not result.records:
        print("The transaction database is empty.", file=sys.stderr)
        return EXIT_OK
    records = transactions.since_cutoff(result.records, since)
    print(
        f"Read {len(result.records)} records in {result.pages} pages"
        + (f"; {len(records)} at or after {format_time(since)}" if since else ""),
        file=sys.stderr,
    )
    if not records:
        print("No transactions in the requested period.", file=sys.stderr)
        return EXIT_OK
    if args.summary:
        return _print_summary(_sessions_for(records, args), args.summary)

    payload, suffix = _transactions_payload(records, args)
    return write_out(
        payload,
        args.file,
        default_name=f"{info.object_id or 'charger'}-transactions.{suffix}",
        yes=args.yes,
    )


def _hours(span) -> str:
    """Render a duration as whole hours and minutes."""
    minutes = int(span.total_seconds() // 60)
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _print_summary(rows: list, grouping: str) -> int:
    """Print charging totals grouped by day, month, socket or tag."""
    if not rows:
        print("No charging sessions to summarise.", file=sys.stderr)
        return EXIT_OK
    groups = transactions.summarise(rows, transactions.GROUPINGS[grouping])
    everything = transactions.total(rows)
    header = grouping.upper()
    table = [
        [
            row.key,
            str(row.sessions),
            f"{row.energy_kwh:.3f}",
            _hours(row.duration),
            "" if row.average_kwh is None else f"{row.average_kwh:.3f}",
        ]
        for row in groups
    ]
    table.append(
        [
            "total",
            str(everything.sessions),
            f"{everything.energy_kwh:.3f}",
            _hours(everything.duration),
            "" if everything.average_kwh is None else f"{everything.average_kwh:.3f}",
        ]
    )
    print_table([header, "SESSIONS", "KWH", "TIME", "KWH/SESSION"], table)
    if everything.incomplete:
        # A session still running, or one whose stop record has aged out of
        # the database, has no energy to count.  Say so rather than letting
        # the totals quietly under-report.
        print(
            f"\n{everything.incomplete} session(s) had no end record, so their "
            "energy is not counted.",
            file=sys.stderr,
        )
    return EXIT_OK


def _erase_transactions(
    charger: AlfenCharger, info: ChargerInfo, args: argparse.Namespace
) -> int:
    """Erase the charger's transaction database, after confirming."""
    if not args.yes:
        print(
            "This erases every charging session and OCPP event the charger "
            "still holds,\nincluding records it has not yet reported to its "
            "backoffice. It cannot be undone.",
            file=sys.stderr,
        )
        if not confirm(f"Erase the transaction database on {info.object_id}?"):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    charger.erase_transactions(is_ahp=info.family == "AHP")
    print("Transaction database erased.")
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "log",
        help="export the charger's own event log since a date (diagnostics)",
        parents=[common],
    )
    sp.add_argument(
        "file",
        nargs="?",
        help="output file ('-' for stdout; default: <object-id>.log to a "
        "terminal, else stdout)",
    )
    sp.add_argument(
        "--since",
        default="today",
        metavar="WHEN",
        help=f"export entries at or after this point (default: today). {SINCE_HELP}",
    )
    sp.add_argument(
        "--all",
        action="store_true",
        help="export everything the charger still holds (same as --since all)",
    )
    sp.add_argument(
        "--range",
        action="store_true",
        help="don't export: report how far back the charger's log reaches",
    )
    sp.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="don't export: print new lines as the charger writes them, until Ctrl+C",
    )
    sp.add_argument(
        "--interval",
        type=float,
        default=FOLLOW_INTERVAL_S,
        metavar="S",
        help=f"seconds between polls while following (default {FOLLOW_INTERVAL_S:g})",
    )
    sp.add_argument(
        "--type",
        action="append",
        type=str.upper,
        choices=LOG_TYPES,
        metavar="TYPE",
        help="only lines of this kind ("
        + ", ".join(t.lower() for t in LOG_TYPES)
        + "); may be given more than once",
    )
    sp.add_argument(
        "-n", "--tail", type=int, metavar="N", help="show only the last N lines"
    )
    sp.add_argument(
        "-g", "--grep", metavar="REGEX", help="only lines matching this regex"
    )
    sp.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="overwrite an existing file without asking",
    )

    sp = sub.add_parser(
        "transactions",
        help="export charging sessions and OCPP events",
        aliases=["tx"],
        parents=[common],
    )
    sp.add_argument(
        "file",
        nargs="?",
        help="output file ('-' for stdout; default: "
        "<object-id>-transactions.<ext> to a terminal, else stdout)",
    )
    sp.add_argument(
        "--since",
        default="all",
        metavar="WHEN",
        help=f"only records at or after this point (default: all). {SINCE_HELP}",
    )
    sp.add_argument("--all", action="store_true", help="every record (the default)")
    sp.add_argument("--socket", type=int, help="only sessions on this socket")
    sp.add_argument(
        "--summary",
        nargs="?",
        const="month",
        choices=sorted(transactions.GROUPINGS),
        help="totals instead of a record-by-record export, grouped by "
        "month (the default), socket or tag",
    )
    sp.add_argument(
        "--json",
        action="store_true",
        help="every parsed record as JSON, not just the charging sessions",
    )
    sp.add_argument(
        "--raw", action="store_true", help="the charger's own record text, unparsed"
    )
    sp.add_argument(
        "--erase",
        action="store_true",
        help="erase the transaction database instead of reading it",
    )
    sp.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="do not prompt (overwrite an output file, or confirm --erase)",
    )


COMMANDS: dict[str, Command] = {
    "log": Command(cmd_log),
    "transactions": Command(cmd_transactions),
    "tx": Command(cmd_transactions),
}
