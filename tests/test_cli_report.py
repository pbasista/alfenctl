"""Tests for the terminal progress line."""

from __future__ import annotations

import sys

import pytest

from alfenctl.cli.report import TerminalReporter
from alfenctl.report import Wait


def _wait(**kw) -> Wait:
    fields = {
        "elapsed_s": 10.0,
        "deadline_s": 900.0,
        "typical_s": 170.0,
        "label": "no response (rebooting)",
        "poll": 1,
        "next_poll_in_s": 5.0,
    }
    return Wait(**{**fields, **kw})


@pytest.fixture
def tty(monkeypatch):
    """Pretend stderr is a terminal, and collect what gets drawn on it.

    The patch goes on pytest's capture *class*, because the instance in
    ``sys.stderr`` is swapped for a fresh one as each test starts.
    """
    drawn: list[str] = []
    monkeypatch.setattr(type(sys.stderr), "isatty", lambda self: True, raising=False)
    monkeypatch.setattr("alfenctl.cli.report.write_live", drawn.append)
    monkeypatch.setattr("alfenctl.cli.report.end_live", lambda: drawn.append("\n"))
    return drawn


def test_the_live_line_is_closed_before_anything_else_prints(capsys, tty) -> None:
    """Otherwise the next message lands on top of a half-drawn bar."""
    report = TerminalReporter()
    report.waiting(_wait())
    report.step("Committing the firmware")
    assert tty[-1] == "\n"
    assert "Committing the firmware..." in capsys.readouterr().out


def test_leaving_the_block_closes_a_line_a_failure_left_open(tty) -> None:
    with TerminalReporter() as report:
        report.waiting(_wait())
    assert tty[-1] == "\n"


def test_nothing_is_closed_that_was_never_opened(capsys, tty) -> None:
    with TerminalReporter() as report:
        report.step("Setting the charger clock")
    assert "\n" not in tty  # no stray newline before the first line of output


def test_the_wait_line_shows_the_countdown_and_the_typical_duration(tty) -> None:
    TerminalReporter().waiting(_wait())
    line = tty[-1]
    assert "poll 1" in line
    assert "next poll in 6s" in line  # 5.0 s left, rounded up to the next second
    assert "elapsed 10s / ~2m50s" in line


def test_a_long_wait_names_the_deadline_instead(tty) -> None:
    """Past the typical duration, "not hung yet" needs saying explicitly."""
    TerminalReporter().waiting(_wait(elapsed_s=300.0))
    line = tty[-1]
    assert "usually ~2m50s" in line and "giving up at 15m00s" in line


def test_a_blocked_poll_draws_without_a_countdown(tty) -> None:
    TerminalReporter().waiting(_wait(next_poll_in_s=None, label="polling..."))
    assert "next poll in" not in tty[-1]


def test_a_pipe_gets_one_line_per_poll_instead_of_a_bar(capsys) -> None:
    report = TerminalReporter()  # capsys makes stderr a pipe, not a tty
    report.polled(_wait())
    report.polled(_wait())  # the same poll again: it moved on, we did not
    report.polled(_wait(poll=2, label="update done"))
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "  poll 1: no response (rebooting)  (elapsed 10s)",
        "  poll 2: update done  (elapsed 10s)",
    ]


def test_debug_logs_the_polls_and_draws_nothing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(type(sys.stderr), "isatty", lambda self: True, raising=False)
    report = TerminalReporter(debug=True)
    assert not report.live
    report.polled(_wait())
    captured = capsys.readouterr()
    assert "[debug] -- reboot wait: poll 1" in captured.err
    assert captured.out == ""


def test_the_upload_bar_is_throttled_but_always_ends_at_100(tty) -> None:
    report = TerminalReporter()
    for sent in range(0, 1_000_000, 100_000):
        report.sending(sent, 1_000_000, 1.0)
    report.sending(1_000_000, 1_000_000, 2.0)
    assert len(tty) < 10  # the mid-stream redraws are collapsed
    assert "100%" in tty[-1]
