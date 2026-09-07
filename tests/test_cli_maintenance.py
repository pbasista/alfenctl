"""Tests for reboots, resets, raw commands and tilt calibration."""

from __future__ import annotations


import pytest

from conftest import (
    patch_wait_until_back,
)

from alfenctl import cli


def test_reboot_asks_then_sends(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("alfenctl.cli.commands.maintenance.REBOOT_SETTLE_S", 0.0)
    patch_wait_until_back(monkeypatch, lambda ch, report=None, deadline_s=0: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(["reboot", "--host", "1.2.3.4"]) == 1
    assert "reboot" not in fake_charger.commands
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert cli.main(["reboot", "--host", "1.2.3.4"]) == 0
    assert fake_charger.commands == ["reboot"]


def test_reboot_no_wait_skips_the_poll(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("alfenctl.cli.commands.maintenance.REBOOT_SETTLE_S", 0.0)

    def fail(*a, **k):
        raise AssertionError("should not wait")

    patch_wait_until_back(monkeypatch, fail)
    assert cli.main(["reboot", "-y", "--no-wait", "--host", "1.2.3.4"]) == 0
    assert fake_charger.commands == ["reboot"]


def test_reboot_reports_a_charger_that_stays_down(
    fake_charger, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("alfenctl.cli.commands.maintenance.REBOOT_SETTLE_S", 0.0)
    patch_wait_until_back(monkeypatch, lambda ch, report=None, deadline_s=0: False)
    assert cli.main(["reboot", "-y", "--host", "1.2.3.4"]) == 1
    assert "did not come back" in capsys.readouterr().err


def test_cmd_sends_the_joined_words(fake_charger, capsys) -> None:
    assert (
        cli.main(["cmd", "-y", "eepromx", "erase", "config", "--host", "1.2.3.4"]) == 0
    )
    assert fake_charger.commands == ["eepromx erase config"]


def test_cmd_asks_before_sending(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(["cmd", "reboot", "--host", "1.2.3.4"]) == 1
    assert not fake_charger.commands


@pytest.mark.parametrize(
    "target, expected",
    [
        ("settings", "clear-settings"),
        ("personal-data", "clear-personal-data"),
    ],
)
def test_erase_targets(fake_charger, target, expected) -> None:
    assert cli.main(["erase", target, "-y", "--host", "1.2.3.4"]) == 0
    assert fake_charger.commands == [expected]


def test_erase_transactions_uses_the_database_call(fake_charger) -> None:
    assert cli.main(["erase", "transactions", "-y", "--host", "1.2.3.4"]) == 0
    assert fake_charger.erased


def test_erase_asks_first(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(["erase", "settings", "--host", "1.2.3.4"]) == 1
    assert not fake_charger.commands
    assert "cannot be undone" in capsys.readouterr().err


# --- Tilt calibration ---------------------------------------------------------------------


def _tilt_props(values, setpoints) -> list[dict]:
    ids = ["2207_0", "2208_0", "2209_0", "2210_0", "2211_0", "2212_0"]
    return [{"id": i, "value": v} for i, v in zip(ids, list(values) + list(setpoints))]


def test_calibrate_tilt_stores_the_live_reading(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _tilt_props(
        (10, -4, 990), (0, 0, 0)
    )
    assert cli.main(["calibrate", "tilt", "-y", "--host", "1.2.3.4"]) == 0
    assert fake_charger.writes[-1] == {
        (0x2210, 0): (10, None),
        (0x2211, 0): (-4, None),
        (0x2212, 0): (990, None),
    }
    out = capsys.readouterr().out
    assert "reading     10" in out
    assert "this position is now upright" in out


def test_calibrate_tilt_prompts_first(fake_charger, capsys, monkeypatch) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _tilt_props(
        (10, -4, 990), (0, 0, 0)
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(["calibrate", "tilt", "--host", "1.2.3.4"]) == cli.EXIT_ERROR
    assert not fake_charger.writes
    assert "must already stand" in capsys.readouterr().err


def test_calibrate_tilt_says_when_nothing_changes(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _tilt_props(
        (10, -4, 990), (10, -4, 990)
    )
    assert cli.main(["calibrate", "tilt", "--host", "1.2.3.4"]) == 0
    assert "already treats its current position" in capsys.readouterr().out
    assert not fake_charger.writes


def test_calibrate_tilt_without_a_sensor(fake_charger, capsys) -> None:
    assert cli.main(["calibrate", "tilt", "--host", "1.2.3.4"]) == cli.EXIT_ERROR
    assert "does not report a tilt sensor" in capsys.readouterr().err


def test_cmd_list_prints_what_the_console_is_known_to_do(capsys) -> None:
    # No --host and no charger: the table is static, so nothing is opened.
    assert cli.main(["cmd", "--list"]) == 0
    captured = capsys.readouterr()
    assert "eepromx erase config" in captured.out
    assert "cansync off" in captured.out  # seen in a real log, in no app
    assert "Tamper detection On" in captured.out  # named, wire form unknown
    assert "unknown, not" in captured.err


def test_cmd_without_a_command_points_at_the_list(fake_charger, capsys) -> None:
    assert cli.main(["cmd", "--host", "1.2.3.4"]) != 0
    assert "--list" in capsys.readouterr().err
    assert fake_charger.commands == []
