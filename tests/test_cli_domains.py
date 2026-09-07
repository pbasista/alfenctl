"""The four curated config commands, from the command line down.

The module tests cover the decoding; what is worth testing here is the wiring
-- that each command reaches its registers, that a `set` sends one batch, and
that the settings the charger accepts and then ignores until it restarts say
so rather than looking as though they worked.
"""

from __future__ import annotations

from alfenctl import cli


def _props(fake_charger, entries: list[dict]) -> None:
    """Add live properties to the charger the fixture pretends to be."""
    fake_charger.docs["/api/prop"]["properties"] += entries


AUTH_PROPS = [
    {"id": "2126_0", "access": 2, "type": 3, "value": 2},
    {"id": "213B_0", "access": 2, "type": 5, "value": 1},
    {"id": "213D_0", "access": 2, "type": 5, "value": 0},
    {"id": "2127_0", "access": 2, "type": 3, "value": 0},
    {"id": "213E_0", "access": 2, "type": 5, "value": 1},
]


def test_auth_show_reads_the_panel(fake_charger, capsys) -> None:
    _props(fake_charger, AUTH_PROPS)
    assert cli.main(["auth", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Authorization" in out
    assert "RFID" in out or "rfid" in out.lower()


def test_auth_set_mode_warns_that_it_waits_for_a_restart(fake_charger, capsys) -> None:
    _props(fake_charger, AUTH_PROPS)
    rc = cli.main(["auth", "set", "--mode", "plug-and-charge", "--host", "1.2.3.4"])
    assert rc == 0
    assert len(fake_charger.writes) == 1
    assert fake_charger.writes[0][(0x2126, 0)][0] == 0
    assert "2126_0 takes effect only after a restart" in capsys.readouterr().err


def test_auth_set_something_else_is_quiet(fake_charger, capsys) -> None:
    _props(fake_charger, AUTH_PROPS)
    rc = cli.main(["auth", "set", "--whitelist", "off", "--host", "1.2.3.4"])
    assert rc == 0
    assert fake_charger.writes[0][(0x213B, 0)][0] == 0
    assert "restart" not in capsys.readouterr().err


def test_auth_set_offline_writes_both_halves_in_one_batch(fake_charger) -> None:
    _props(fake_charger, AUTH_PROPS)
    assert cli.main(["auth", "set", "--offline", "any", "--host", "1.2.3.4"]) == 0
    written = fake_charger.writes[0]
    assert written[(0x2127, 0)][0] == 1
    assert written[(0x213E, 0)][0] == 1


OCPP_PROPS = [
    {"id": "2071_1", "access": 2, "type": 9, "value": "ws://csms.example"},
    {"id": "2071_2", "access": 2, "type": 9, "value": "/ocpp"},
    {"id": "2085_0", "access": 2, "type": 7, "value": 900},
    {"id": "2117_0", "access": 2, "type": 5, "value": 0},
]


def test_ocpp_show_reads_the_backoffice_block(fake_charger, capsys) -> None:
    _props(fake_charger, OCPP_PROPS)
    assert cli.main(["ocpp", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "ws://csms.example" in out


def test_ocpp_set_url_warns_that_it_waits_for_a_restart(fake_charger, capsys) -> None:
    _props(fake_charger, OCPP_PROPS)
    rc = cli.main(
        ["ocpp", "set", "--wired-url", "ws://new.example", "--host", "1.2.3.4"]
    )
    assert rc == 0
    assert fake_charger.writes[0][(0x2071, 1)][0] == "ws://new.example"
    assert "2071_1 takes effect only after a restart" in capsys.readouterr().err


def test_ocpp_set_heartbeat_writes_the_register_that_is_not_read_only(
    fake_charger, capsys
) -> None:
    _props(fake_charger, OCPP_PROPS)
    assert cli.main(["ocpp", "set", "--heartbeat", "300", "--host", "1.2.3.4"]) == 0
    written = fake_charger.writes[0]
    assert written[(0x2085, 0)][0] == 300
    assert (0x2086, 0) not in written
    assert "restart" not in capsys.readouterr().err


LB_PROPS = [
    {"id": "2064_0", "access": 2, "type": 5, "value": 1},
    {"id": "2067_0", "access": 2, "type": 8, "value": 40.0},
    {"id": "2068_0", "access": 2, "type": 8, "value": 6.0},
    {"id": "3280_1", "access": 2, "type": 5, "value": 0},
]


def test_loadbalancing_show_and_its_alias(fake_charger, capsys) -> None:
    _props(fake_charger, LB_PROPS)
    assert cli.main(["lb", "--host", "1.2.3.4"]) == 0
    first = capsys.readouterr().out
    assert cli.main(["loadbalancing", "show", "--host", "1.2.3.4"]) == 0
    assert capsys.readouterr().out == first


def test_loadbalancing_set_safe_current_sends_one_batch(fake_charger) -> None:
    _props(fake_charger, LB_PROPS)
    rc = cli.main(["loadbalancing", "set", "--safe-current", "10", "--host", "1.2.3.4"])
    assert rc == 0
    assert len(fake_charger.writes) == 1
    assert fake_charger.writes[0][(0x2068, 0)][0] == 10.0


def test_network_show_lists_what_it_can_reach(fake_charger, capsys) -> None:
    _props(
        fake_charger,
        [
            {"id": "328F_0", "access": 1, "type": 5, "value": 1},
            {"id": "328A_0", "access": 2, "type": 9, "value": "home-wifi"},
            {"id": "3284_0", "access": 2, "type": 5, "value": 1},
        ],
    )
    assert cli.main(["network", "--host", "1.2.3.4"]) == 0
    assert "home-wifi" in capsys.readouterr().out
