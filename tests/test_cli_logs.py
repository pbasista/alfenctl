"""Tests for ``alfenctl logs`` and ``alfenctl transactions``."""

from __future__ import annotations

import json
from datetime import datetime, timezone


from alfenctl import cli


def test_log_stdout_and_filters(fake_charger, capsys, monkeypatch) -> None:
    """log to stdout (piped) prints lines; --grep/-n filter them."""
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert cli.main(["log", "-", "--all", "--host", "192.168.11.42"]) == 0
    out = capsys.readouterr().out
    assert "fw_update.c:212" in out
    assert "fw_update.c:388" in out


def test_log_stdout_grep_and_tail(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert (
        cli.main(
            [
                "log",
                "-",
                "--all",
                "-g",
                "licensed",
                "-n",
                "1",
                "--host",
                "192.168.11.42",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Rejecting upload" in out
    assert "upload started" not in out


def test_log_writes_default_file_with_prompt(
    fake_charger, capsys, monkeypatch, tmp_path
) -> None:
    """Default filename on a tty; asks before overwriting; -y bypasses."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    # first write: no prompt
    assert cli.main(["log", "--all", "--host", "192.168.11.42"]) == 0
    assert (tmp_path / "ACE0781464.log").read_text().count("\n") == 2
    # existing file, decline: abort, file untouched
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(["log", "--all", "--host", "192.168.11.42"]) == 1
    # existing file, accept: overwrite
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert cli.main(["log", "--all", "--host", "192.168.11.42"]) == 0
    # -y bypasses the prompt entirely
    monkeypatch.setattr(
        "builtins.input", lambda prompt: (_ for _ in ()).throw(AssertionError("asked"))
    )
    assert cli.main(["log", "-y", "--all", "--host", "192.168.11.42"]) == 0
    assert "Rejecting upload" in (tmp_path / "ACE0781464.log").read_text()


def test_transactions_csv_lists_sessions(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert cli.main(["transactions", "-", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("transaction_id,socket,start_time")
    assert len(out) == 3  # header plus two sessions; the meter value is not one
    assert ",15.250," in out[1]
    assert "04A1B2C3D4E5" in out[1]


def test_transactions_socket_filter(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert cli.main(["tx", "-", "--socket", "2", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2 and "04FFEE1122" in out[1]


def test_transactions_json_keeps_every_record(
    fake_charger, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert cli.main(["tx", "-", "--json", "--host", "1.2.3.4"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [r["kind"] for r in doc] == ["transaction", "meter-value", "transaction"]
    assert all("raw" in r for r in doc)


def test_transactions_raw_is_the_charger_text(
    fake_charger, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert cli.main(["tx", "-", "--raw", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "1024_tx: id = 0000A1B2" in out


def test_transactions_since_filters(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert cli.main(["tx", "-", "--since", "2026-08-30", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "04FFEE1122" in out and "04A1B2C3D4E5" not in out


def test_transactions_empty_database(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    fake_charger.docs["/api/transactions"] = []
    assert cli.main(["tx", "-", "--host", "1.2.3.4"]) == 0
    assert "empty" in capsys.readouterr().err


def test_transactions_erase_asks_first(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(["tx", "--erase", "--host", "1.2.3.4"]) == 1
    assert not fake_charger.erased
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert cli.main(["tx", "--erase", "--host", "1.2.3.4"]) == 0
    assert fake_charger.erased


def _dated_log(fake_charger, count: int, *, page: int = 4) -> None:
    """Fill the fake charger with ``count`` log lines, one an hour, ending now."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    fake_charger.log_page_lines = page
    fake_charger.docs["/api/log"] = [
        f"{1000 + i * 128}_"
        f"{(now - timedelta(hours=count - 1 - i)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z"
        f":INFO:taskMain.c:{100 + i}:hour minus {count - 1 - i}"
        for i in range(count)
    ]


def test_log_since_limits_what_is_exported(fake_charger, capsys, monkeypatch) -> None:
    """--since keeps only entries at or after the cutoff."""
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    _dated_log(fake_charger, 48)  # two days of hourly lines
    assert cli.main(["log", "-", "--since", "6h", "--host", "192.168.11.42"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) <= 7  # six hours back, to within the page the cutoff fell in
    assert "hour minus 0" in out[-1]
    assert "hour minus 47" not in "\n".join(out)


def test_log_since_default_is_today(fake_charger, capsys, monkeypatch) -> None:
    """With no --since, the export starts at local midnight."""

    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    _dated_log(fake_charger, 48)
    assert cli.main(["log", "-", "--host", "192.168.11.42"]) == 0
    midnight = (
        datetime.now(timezone.utc)
        .astimezone()
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    for line in capsys.readouterr().out.splitlines():
        stamp = datetime.strptime(line.split("_")[1][:23], "%Y-%m-%dT%H:%M:%S.%f")
        assert stamp.replace(tzinfo=timezone.utc) >= midnight


def test_log_all_beats_the_default_cutoff(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    _dated_log(fake_charger, 48)
    assert cli.main(["log", "-", "--all", "--host", "192.168.11.42"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 48


def test_log_rejects_a_bad_since(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert cli.main(["log", "-", "--since", "whenever", "--host", "1.2.3.4"]) == 1
    assert "unrecognised date/time" in capsys.readouterr().err


def test_log_range_reports_the_available_span(
    fake_charger, capsys, monkeypatch
) -> None:
    """--range probes for the oldest entry instead of exporting anything."""
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    _dated_log(fake_charger, 48)
    assert cli.main(["log", "--range", "--host", "192.168.11.42"]) == 0
    out = capsys.readouterr().out
    assert "oldest entry" in out and "newest entry" in out
    assert "ACE0781464" in out
    assert "hour minus" not in out  # it did not dump the log


def test_log_range_on_an_empty_log(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    fake_charger.docs["/api/log"] = []
    assert cli.main(["log", "--range", "--host", "192.168.11.42"]) == 0
    assert "log is empty" in capsys.readouterr().err


def test_log_export_on_an_empty_log(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    fake_charger.docs["/api/log"] = []
    assert cli.main(["log", "-", "--all", "--host", "192.168.11.42"]) == 0
    assert "log is empty" in capsys.readouterr().err


def test_log_reports_an_empty_period(fake_charger, capsys, monkeypatch) -> None:
    """A log that exists but holds nothing recent enough says so differently."""
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    _dated_log(fake_charger, 48)
    assert cli.main(["log", "-", "--since", "2030-01-01", "--host", "1.2.3.4"]) == 0
    assert "No log lines in the requested period" in capsys.readouterr().err


def test_log_warns_when_the_charger_holds_less_than_asked(
    fake_charger, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    _dated_log(fake_charger, 6)  # only six hours of log
    assert cli.main(["log", "-", "--since", "3w", "--host", "192.168.11.42"]) == 0
    assert "only keeps its log back to" in capsys.readouterr().err


# --- Log filtering and following ----------------------------------------------------------


def test_log_type_filter_keeps_only_that_kind(
    fake_charger, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert cli.main(["log", "--all", "--type", "error", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Rejecting upload" in out  # the one ERROR line
    assert "Firmware upload started" not in out  # the INFO line


def test_log_type_filter_takes_several_kinds(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    argv = ["log", "--all", "--type", "error", "--type", "info", "--host", "1.2.3.4"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "Rejecting upload" in out
    assert "Firmware upload started" in out


def test_log_follow_prints_the_backlog_then_new_lines(
    fake_charger, capsys, monkeypatch
) -> None:
    """Ctrl+C ends the loop, as it does for a user."""
    stored = fake_charger.docs["/api/log"]
    fake_charger.log_page_lines = 4
    polls: list[int] = []

    def fake_sleep(seconds: float) -> None:
        polls.append(len(polls))
        if len(polls) > 2:
            raise KeyboardInterrupt
        stored.append(
            f"500{len(polls)}_2026-08-29T13:00:0{len(polls)}.000Z:INFO:x.c:1:"
            f"fresh line {len(polls)}"
        )

    monkeypatch.setattr("time.sleep", fake_sleep)
    assert cli.main(["log", "--follow", "--host", "1.2.3.4"]) == cli.EXIT_INTERRUPTED
    out = capsys.readouterr().out
    assert "fresh line 1" in out and "fresh line 2" in out
    # The backlog is printed once, and no line is repeated by the next poll.
    assert out.count("fresh line 1") == 1


def test_log_follow_reports_a_gap(fake_charger, capsys, monkeypatch) -> None:
    """A whole page of new lines means the ones in between are gone."""
    stored = fake_charger.docs["/api/log"]
    fake_charger.log_page_lines = 2
    rounds: list[int] = []

    def fake_sleep(seconds: float) -> None:
        rounds.append(1)
        if len(rounds) > 1:
            raise KeyboardInterrupt
        stored.extend(
            f"50{n}0_2026-08-29T13:00:0{n}.000Z:INFO:x.c:1:burst {n}" for n in range(4)
        )

    monkeypatch.setattr("time.sleep", fake_sleep)
    assert cli.main(["log", "-f", "--host", "1.2.3.4"]) == cli.EXIT_INTERRUPTED
    assert "some lines were skipped" in capsys.readouterr().err


def test_log_follow_honours_the_type_filter(fake_charger, capsys, monkeypatch) -> None:
    def fake_sleep(seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep)
    argv = ["log", "--follow", "--type", "error", "--host", "1.2.3.4"]
    assert cli.main(argv) == cli.EXIT_INTERRUPTED
    out = capsys.readouterr().out
    assert "Rejecting upload" in out
    assert "Firmware upload started" not in out


# --- what the charge log is usually opened to answer -------------------------------------------


def test_transactions_summary_totals_by_month(fake_charger, capsys) -> None:
    assert cli.main(["tx", "--summary", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    # Both fixture sessions started in August 2026: 15.250 + 7.000 kWh.
    assert "2026-08" in out
    assert "22.250" in out
    assert "total" in out


def test_transactions_summary_by_socket(fake_charger, capsys) -> None:
    assert cli.main(["tx", "--summary", "socket", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "socket 1" in out and "15.250" in out
    assert "socket 2" in out and "7.000" in out


def test_transactions_summary_by_tag(fake_charger, capsys) -> None:
    assert cli.main(["tx", "--summary", "tag", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "04A1B2C3D4E5" in out and "04FFEE1122" in out


def test_transactions_summary_honours_the_socket_filter(fake_charger, capsys) -> None:
    rc = cli.main(["tx", "--summary", "--socket", "2", "--host", "1.2.3.4"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "7.000" in out and "15.250" not in out


def test_transactions_summary_says_when_a_session_could_not_be_counted(
    fake_charger, capsys
) -> None:
    fake_charger.docs["/api/transactions"].append(
        "4096_txstart: id = 0000E5F6, socket1, "
        "2026-08-31 08:00:00 1300.000kWh 04A1B2C3D4E5 Y"
    )
    assert cli.main(["tx", "--summary", "--host", "1.2.3.4"]) == 0
    captured = capsys.readouterr()
    assert "22.250" in captured.out  # the unfinished one adds no energy
    assert "no end record" in captured.err
