"""Tests for licences, passwords and write-only secrets."""

from __future__ import annotations


import pytest

from conftest import (
    status_error,
    patch_charger,
)

from alfenctl import cli


def test_license_show_unsupported_firmware(fake_charger, capsys) -> None:
    """The default fake charger reports no license properties at all."""
    assert cli.main(["license", "show", "--host", "1.2.3.4"]) == 0
    assert "does not support license keys" in capsys.readouterr().out


def test_license_show_prints_installed_features(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += [
        {"id": "21A0_0", "value": "0011.2233.4455.6677"},
        {"id": "21A1_0", "value": "0011.2233.4455.6677.8899.AABB"},
        {"id": "21A2_0", "value": 0x1000},  # personalized display
    ]
    assert cli.main(["license", "show", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Personalized display" in out
    assert "0011.2233.4455.6677.8899.AABB" in out
    assert "Logo upload" in out and "licensed" in out
    assert "0x1000" in out


def test_license_set_writes_the_normalized_key(fake_charger, capsys) -> None:
    assert cli.main(["license", "set", "11.22.33.44.55.66", "--host", "1.2.3.4"]) == 0
    assert fake_charger.writes[-1] == {
        (0x21A1, 0): ("0011.0022.0033.0044.0055.0066", None)
    }
    out = capsys.readouterr().out
    assert "License key set to 0011.0022.0033.0044.0055.0066" in out
    assert "reboot on its own" in out


def test_license_set_rejects_a_bad_key(fake_charger, capsys) -> None:
    assert cli.main(["license", "set", "not-a-key", "--host", "1.2.3.4"]) == 1
    assert "not a valid license key" in capsys.readouterr().err
    assert not fake_charger.writes


def test_password_set_prompts_when_not_given(fake_charger, monkeypatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt: "s3cret")
    assert cli.main(["password", "set", "--host", "1.2.3.4"]) == 0
    assert fake_charger.passwords == [("set", "s3cret", None)]


def test_password_set_takes_it_on_the_command_line(fake_charger) -> None:
    assert cli.main(["password", "set", "hunter2", "--host", "1.2.3.4"]) == 0
    assert fake_charger.passwords == [("set", "hunter2", None)]


def test_password_rejects_an_empty_one(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt: "")
    assert cli.main(["password", "set", "--host", "1.2.3.4"]) == 1
    assert "empty password" in capsys.readouterr().err


def test_password_temporary_defaults_to_a_day(fake_charger) -> None:
    assert cli.main(["password", "temporary", "temp1", "--host", "1.2.3.4"]) == 0
    assert fake_charger.passwords == [
        ("temporary", "temp1", cli.DEFAULT_TEMP_PASSWORD_HOURS)
    ]


def test_password_temporary_hours(fake_charger) -> None:
    assert (
        cli.main(["password", "temporary", "t", "--hours", "8", "--host", "1.2.3.4"])
        == 0
    )
    assert fake_charger.passwords[0][2] == 8


def test_password_recover_runs_without_logging_in(fake_charger, capsys) -> None:
    """The point of recovery is that the password is unknown."""
    assert cli.main(["password", "recover", "AB12-CD34", "--host", "1.2.3.4"]) == 0
    assert fake_charger.passwords == [("recover", "AB12-CD34", None)]
    assert not fake_charger.logged_in
    assert "reset to the charger's default" in capsys.readouterr().out


@pytest.mark.parametrize(
    "code, body, expected",
    [
        (403, "", "code is incorrect"),
        (429, '{"version":1,"lockout_remaining_seconds":300}', "for 5.0 minutes"),
        (503, "", "not available on this charging station"),
        (500, "", "HTTP 500"),
    ],
)
def test_password_recover_explains_a_refusal(
    fake_charger, capsys, code, body, expected
) -> None:
    fake_charger.recovery_error = status_error(code, body)
    assert cli.main(["password", "recover", "WRONG", "--host", "1.2.3.4"]) == 1
    assert expected in capsys.readouterr().err


def test_password_pin_sets_it(fake_charger) -> None:
    assert cli.main(["password", "pin", "1234", "--host", "1.2.3.4"]) == 0
    assert fake_charger.end_user_pin == "1234"


def test_password_pin_rejects_a_bad_pin(fake_charger, capsys) -> None:
    assert cli.main(["password", "pin", "12", "--host", "1.2.3.4"]) == 1
    assert "4 to 6 digits" in capsys.readouterr().err
    assert fake_charger.end_user_pin == "unset"  # untouched


def test_password_pin_allow_empty(fake_charger) -> None:
    assert cli.main(["password", "pin", "--allow-empty", "--host", "1.2.3.4"]) == 0
    assert fake_charger.end_user_pin == ""


def test_password_pin_disable(fake_charger) -> None:
    assert cli.main(["password", "pin", "--disable", "--host", "1.2.3.4"]) == 0
    assert fake_charger.end_user_pin is None


# --- Write-only secrets -------------------------------------------------------------------


def test_secret_list_needs_no_charger(capsys, monkeypatch) -> None:
    patch_charger(monkeypatch, lambda *a, **k: pytest.fail("connected to a charger"))
    assert cli.main(["secret"]) == 0
    out = capsys.readouterr().out
    assert "auth-key" in out and "client-cert" in out
    assert "never reads them back" in out


def test_secret_set_installs_a_value(fake_charger, capsys) -> None:
    assert cli.main(["secret", "set", "auth-key", "s3cret", "--host", "1.2.3.4"]) == 0
    assert fake_charger.domain_items == [(0, b"s3cret")]
    assert "Installed auth-key on ACE0781464" in capsys.readouterr().out


def test_secret_set_prompts_when_the_value_is_omitted(
    fake_charger, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt: "typed-in")
    assert cli.main(["secret", "set", "proxy-password", "--host", "1.2.3.4"]) == 0
    assert fake_charger.domain_items == [(2, b"typed-in")]


def test_secret_set_installs_a_certificate_file(fake_charger, capsys, tmp_path) -> None:
    pem = tmp_path / "root.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\nMIIB\n")
    assert cli.main(["secret", "set", "ca-cert", str(pem), "--host", "1.2.3.4"]) == 0
    assert fake_charger.domain_items == [(17, pem.read_bytes())]
    assert f"from {pem}" in capsys.readouterr().out


def test_secret_set_refuses_a_certificate_without_a_file(fake_charger, capsys) -> None:
    assert cli.main(["secret", "set", "ca-cert", "--host", "1.2.3.4"]) == cli.EXIT_ERROR
    assert "takes a file" in capsys.readouterr().err
    assert not fake_charger.domain_items


def test_secret_set_reports_a_missing_file(fake_charger, capsys) -> None:
    assert (
        cli.main(["secret", "set", "ca-cert", "/no/such.pem", "--host", "1.2.3.4"])
        == cli.EXIT_ERROR
    )
    assert "cannot read /no/such.pem" in capsys.readouterr().err


def test_secret_set_rejects_an_unknown_name(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["secret", "set", "nonsense", "value"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
