"""Tests for ``alfenctl scn`` -- the Smart Charging Network commands."""

from __future__ import annotations


from conftest import (
    FakeCharger,
    patch_charger,
    patch_discover,
    patch_wait_until_back,
)

from alfenctl import cli, scn
from alfenctl.charger import ChargerInfo
from alfenctl.discovery import Station


def _scn_prop(sub: int, value) -> dict:
    return {"id": f"2180_{sub:X}", "value": value}


def _scn_info(object_id: str) -> ChargerInfo:
    return ChargerInfo(
        object_id=object_id,
        identity=object_id,
        model="NG910-60027",
        family="NG",
        firmware="7.4.5-4415",
        firmware_version=(7, 4, 5),
        sockets=1,
    )


def _scn_member(
    ip: str, object_id: str, name: str, socket_id: int, count: int = 1
) -> FakeCharger:
    """A FakeCharger standing in for one other SCN member, found on the LAN."""
    member = FakeCharger()
    member.station = Station(
        ip=ip, port=443, hostname=f"alfen-{object_id.lower()}.local."
    )
    member.info_override = _scn_info(object_id)
    member.docs["/api/prop"]["properties"] = [
        _scn_prop(1, name),
        _scn_prop(2, socket_id),
        _scn_prop(3, count),
        _scn_prop(4, 900),
        _scn_prop(5, 32.0),
        _scn_prop(6, 6.0),
        _scn_prop(10, 32.0),
    ]
    return member


def _scn_setup(monkeypatch, *members: FakeCharger) -> dict[str, FakeCharger]:
    """Wire discover()/AlfenCharger so each station.ip resolves to its own fake."""
    by_ip = {m.station.ip: m for m in members}
    patch_discover(monkeypatch, lambda duration: [m.station for m in members])
    patch_charger(
        monkeypatch, lambda station, username, password, **kw: by_ip[station.ip]
    )
    return by_ip


def test_scn_status_not_a_member(fake_charger, capsys) -> None:
    assert cli.main(["scn", "status", "--host", "1.2.3.4"]) == 0
    assert "not a member" in capsys.readouterr().out


def test_scn_status_shows_membership(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += [
        _scn_prop(1, "garage"),
        _scn_prop(2, 0),
        _scn_prop(3, 2),
        _scn_prop(4, 600),
        _scn_prop(5, 40.0),
        _scn_prop(6, 10.0),
        _scn_prop(10, 40.0),
    ]
    assert cli.main(["scn", "status", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "member of Smart Charging Network 'garage'" in out
    assert "Socket id       0" in out
    assert "--peers" in out


def test_scn_status_with_peers(monkeypatch, capsys) -> None:
    primary = _scn_member("10.0.0.1", "PRIMARY", "garage", 0)
    peer = _scn_member("10.0.0.2", "PEER", "garage", 1)
    other = _scn_member("10.0.0.3", "OTHER", "different-net", 0)
    _scn_setup(monkeypatch, primary, peer, other)
    assert cli.main(["scn", "status", "--peers", "--host", "10.0.0.1"]) == 0
    out = capsys.readouterr().out
    assert "2 member(s) found" in out
    assert "PRIMARY" in out and "this station" in out
    assert "PEER" in out
    assert "OTHER" not in out


def test_scn_create_writes_defaults(fake_charger, capsys, monkeypatch) -> None:
    patch_discover(monkeypatch, lambda duration: [])
    patch_wait_until_back(monkeypatch, lambda ch, report=None, deadline_s=0: True)
    assert cli.main(["scn", "create", "garage", "-y", "--host", "1.2.3.4"]) == 0
    write = fake_charger.writes[-1]
    assert write[scn.P_NAME] == ("garage", None)
    assert write[scn.P_SOCKET_ID] == (0, None)
    assert write[scn.P_SOCKET_COUNT] == (1, None)
    assert write[scn.P_TOTAL_CURRENT] == (32.0, None)
    assert fake_charger.commands == ["reboot"]
    assert "Created 'garage'" in capsys.readouterr().out


def test_scn_create_refuses_when_already_a_member(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += [_scn_prop(1, "existing")]
    assert cli.main(["scn", "create", "garage", "-y", "--host", "1.2.3.4"]) == 1
    assert "already a member" in capsys.readouterr().err


def test_scn_create_refuses_a_bad_name(fake_charger, capsys) -> None:
    assert cli.main(["scn", "create", "way-too-long", "-y", "--host", "1.2.3.4"]) == 1
    assert "longer than" in capsys.readouterr().err


def test_scn_create_refuses_a_name_clash(monkeypatch, capsys) -> None:
    primary = _scn_member("10.0.0.1", "PRIMARY", "", 0)
    other = _scn_member("10.0.0.2", "OTHER", "garage", 0)
    _scn_setup(monkeypatch, primary, other)
    assert cli.main(["scn", "create", "garage", "-y", "--host", "10.0.0.1"]) == 1
    assert "already in use" in capsys.readouterr().err


def test_scn_join_no_existing_members_found(fake_charger, capsys, monkeypatch) -> None:
    patch_discover(monkeypatch, lambda duration: [])
    assert cli.main(["scn", "join", "garage", "-y", "--host", "1.2.3.4"]) == 1
    assert "no existing members" in capsys.readouterr().err


def test_scn_join_writes_and_syncs_existing_members(monkeypatch, capsys) -> None:
    primary = _scn_member("10.0.0.1", "PRIMARY", "", 0)
    member0 = _scn_member("10.0.0.2", "MEMBER0", "garage", 0)
    member1 = _scn_member("10.0.0.3", "MEMBER1", "garage", 1)
    _scn_setup(monkeypatch, primary, member0, member1)
    patch_wait_until_back(monkeypatch, lambda ch, report=None, deadline_s=0: True)
    assert cli.main(["scn", "join", "garage", "-y", "--host", "10.0.0.1"]) == 0
    write = primary.writes[-1]
    assert write[scn.P_NAME] == ("garage", None)
    assert write[scn.P_SOCKET_ID] == (2, None)  # past both existing (0 and 1)
    assert write[scn.P_SOCKET_COUNT] == (3, None)
    assert member0.writes[-1][scn.P_SOCKET_COUNT] == (3, None)
    assert member1.writes[-1][scn.P_SOCKET_COUNT] == (3, None)
    assert primary.commands == ["reboot"]
    assert member0.commands == []  # only the joining device reboots
    out = capsys.readouterr().out
    assert "Joined 'garage'" in out
    assert "Updated 2/2 other member(s)" in out


def test_scn_join_refuses_when_already_a_member(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += [_scn_prop(1, "existing")]
    assert cli.main(["scn", "join", "garage", "-y", "--host", "1.2.3.4"]) == 1
    assert "already a member" in capsys.readouterr().err


def test_scn_leave_not_a_member(fake_charger, capsys) -> None:
    assert cli.main(["scn", "leave", "-y", "--host", "1.2.3.4"]) == 1
    assert "not a member" in capsys.readouterr().err


def test_scn_leave_clears_and_syncs_remaining_members(monkeypatch, capsys) -> None:
    primary = _scn_member("10.0.0.1", "PRIMARY", "garage", 0)
    member1 = _scn_member("10.0.0.2", "MEMBER1", "garage", 1)
    _scn_setup(monkeypatch, primary, member1)
    assert cli.main(["scn", "leave", "-y", "--host", "10.0.0.1"]) == 0
    assert primary.writes[-1] == {scn.P_NAME: ("", None)}
    assert member1.writes[-1][scn.P_SOCKET_COUNT] == (1, None)
    out = capsys.readouterr().out
    assert "PRIMARY removed from 'garage'" in out
    assert "Updated 1/1 other member(s)" in out
