"""Tests for discovery data and progress rendering (pure logic, no network)."""

from __future__ import annotations

from alfenctl.discovery import Station
from alfenctl.progress import PROGRESS_BAR_WIDTH, bar, fmt_duration


def test_object_id_from_hostname() -> None:
    st = Station(ip="192.168.11.42", port=443, hostname="alfen-ace0781464.local.")
    assert st.object_id == "ace0781464"


def test_object_id_without_dash() -> None:
    st = Station(ip="10.0.0.1", port=80, hostname="charger.local.")
    assert st.object_id == "charger"


def test_object_id_empty_hostname() -> None:
    assert Station(ip="10.0.0.1", port=443).object_id == ""


def test_fmt_duration_seconds() -> None:
    assert fmt_duration(0) == "0s"
    assert fmt_duration(42) == "42s"
    assert fmt_duration(59.9) == "59s"


def test_fmt_duration_minutes() -> None:
    assert fmt_duration(60) == "1m00s"
    assert fmt_duration(125) == "2m05s"
    assert fmt_duration(97) == "1m37s"


def test_bar_half() -> None:
    b = bar(0.5)
    assert b.count("#") == PROGRESS_BAR_WIDTH // 2
    assert b.count("-") == PROGRESS_BAR_WIDTH - PROGRESS_BAR_WIDTH // 2


def test_bar_clamped() -> None:
    assert bar(-0.5) == "-" * PROGRESS_BAR_WIDTH
    assert bar(1.0) == "#" * PROGRESS_BAR_WIDTH
    assert bar(2.0) == "#" * PROGRESS_BAR_WIDTH
