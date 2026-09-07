"""Tests for the Smart Charging Network membership module."""

from __future__ import annotations

import httpx

from alfenctl import scn


def _prop(sub: int, value) -> dict:
    return {"id": f"2180_{sub:X}", "value": value}


def test_read_membership_not_in_a_network(make_charger) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"properties": []})

    with make_charger(handler) as ch:
        membership = scn.read_membership(ch)
    assert not membership.in_network
    assert membership.name == ""
    # Falls back to the app's own defaults for the settings.
    assert membership.settings.alternating_period_s == scn.DEFAULT_ALTERNATING_PERIOD_S
    assert membership.settings.total_current_a == scn.DEFAULT_TOTAL_CURRENT_A


def test_read_membership_parses_all_properties(make_charger) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "properties": [
                    _prop(1, "MYSITE"),
                    _prop(2, 2),
                    _prop(3, 5),
                    _prop(4, 1200),
                    _prop(5, 40.0),
                    _prop(6, 10.0),
                    _prop(10, 40.0),
                ]
            },
        )

    with make_charger(handler) as ch:
        membership = scn.read_membership(ch)
    assert membership.in_network
    assert membership.name == "MYSITE"
    assert membership.socket_id == 2
    assert membership.socket_count == 5
    assert membership.settings == scn.ScnSettings(
        alternating_period_s=1200,
        total_current_a=40.0,
        socket_safe_current_a=10.0,
        total_safe_current_a=40.0,
    )


def test_validate_name() -> None:
    assert scn.validate_name("  garage  ") == "garage"
    try:
        scn.validate_name("   ")
    except scn.ScnError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("expected ScnError")
    try:
        scn.validate_name("toolongname")
    except scn.ScnError as exc:
        assert "longer" in str(exc)
    else:
        raise AssertionError("expected ScnError")


def test_create_writes_are_the_apps_defaults_for_a_single_member() -> None:
    settings = scn.ScnSettings(
        alternating_period_s=900,
        total_current_a=32.0,
        socket_safe_current_a=6.0,
        total_safe_current_a=32.0,
    )
    writes = scn.create_writes("garage", 1, settings)
    assert writes[scn.P_NAME] == ("garage", None)
    assert writes[scn.P_SOCKET_ID] == (0, None)
    assert writes[scn.P_SOCKET_COUNT] == (1, None)
    assert writes[scn.P_ALT_PERIOD] == (900, None)
    assert writes[scn.P_TOTAL_CURRENT] == (32.0, None)
    assert writes[scn.P_SOCKET_SAFE_CURRENT] == (6.0, None)
    assert writes[scn.P_TOTAL_SAFE_CURRENT] == (32.0, None)


def test_sync_writes_do_not_touch_name_or_socket_id() -> None:
    settings = scn.ScnSettings(600, 20.0, 6.0, 20.0)
    writes = scn.sync_writes(3, settings)
    assert scn.P_NAME not in writes
    assert scn.P_SOCKET_ID not in writes
    assert writes[scn.P_SOCKET_COUNT] == (3, None)
    assert writes[scn.P_ALT_PERIOD] == (600, None)


def test_join_writes_include_name_and_id_plus_synced_settings() -> None:
    settings = scn.ScnSettings(600, 20.0, 6.0, 20.0)
    writes = scn.join_writes("garage", 2, 3, settings)
    assert writes[scn.P_NAME] == ("garage", None)
    assert writes[scn.P_SOCKET_ID] == (2, None)
    assert writes[scn.P_SOCKET_COUNT] == (3, None)


def test_leave_writes_only_clear_the_name() -> None:
    assert scn.leave_writes() == {scn.P_NAME: ("", None)}


def _peer(socket_id: int, own_sockets: int = 1) -> scn.Peer:
    return scn.Peer(
        object_id=f"CS{socket_id}",
        identity=f"CS{socket_id}",
        own_sockets=own_sockets,
        membership=scn.Membership(
            name="garage",
            socket_id=socket_id,
            socket_count=1,
            settings=scn.ScnSettings(900, 32.0, 6.0, 32.0),
        ),
    )


def test_next_socket_id_with_no_members() -> None:
    assert scn.next_socket_id([]) == 0


def test_next_socket_id_appends_past_a_single_socket_member() -> None:
    assert scn.next_socket_id([_peer(0)]) == 1


def test_next_socket_id_appends_past_a_multi_socket_member() -> None:
    assert scn.next_socket_id([_peer(0, own_sockets=2)]) == 2


def test_next_socket_id_appends_past_the_highest_of_several_members() -> None:
    members = [_peer(0), _peer(3, own_sockets=2), _peer(1)]
    assert scn.next_socket_id(members) == 5
