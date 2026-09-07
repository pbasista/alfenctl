"""Tests for the charger client, driven through httpx's MockTransport."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable

import httpx
import pytest

import alfenctl.charger as charger_mod

from alfenctl.discovery import Station

from alfenctl.charger import (
    CONNECT_TIMEOUT_S,
    UPLOAD_WRITE_SIZE,
    AlfenCharger,
    UploadError,
    _FixedChunkStream,
    parse_prop_id,
)

Handler = Callable[[httpx.Request], httpx.Response]


def test_parse_prop_id() -> None:
    assert parse_prop_id("100A_0") == (0x100A, 0)
    assert parse_prop_id("205E_00") == (0x205E, 0)
    assert parse_prop_id("junk") is None
    assert parse_prop_id("1_2_3") is None
    assert parse_prop_id("20ZZ_0") is None


def test_login_token_sets_bearer_header(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/login":
            return httpx.Response(200, json={"access": "tok", "refresh": "r"})
        return httpx.Response(200, json={"categories": ["generic"]})

    with make_charger(handler) as ch:
        ch.login()
        cats = ch.categories()
    assert cats == ["generic"]
    assert seen[0].headers.get("authorization") is None  # login itself
    assert seen[1].headers["authorization"] == "Bearer tok"  # subsequent calls


def test_login_cookie_session_carries_no_bearer(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"categories": []})  # empty-body login

    with make_charger(handler) as ch:
        ch.login()
        assert ch.categories() == []
    assert all(r.headers.get("authorization") is None for r in seen)


def test_old_generation_sends_basic_auth(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"categories": []})

    with make_charger(handler, https=False) as ch:
        ch.categories()
    expected = base64.b64encode(b"admin:secret").decode()
    assert seen[0].headers["authorization"] == f"Basic {expected}"


def test_authed_relogin_and_retry_on_401(make_charger) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/login":
            return httpx.Response(200)
        if calls.count("/api/prop") == 1:
            return httpx.Response(401)
        return httpx.Response(200, json={"properties": [], "total": 0})

    with make_charger(handler) as ch:
        assert ch.properties("generic") == {}
    assert calls == ["/api/prop", "/api/login", "/api/prop"]


def test_firmware_status_recovers_the_session_after_a_reboot(make_charger) -> None:
    """The poll after the charger comes back re-authenticates by itself.

    The session is bound to the TCP connection, so it does not survive the
    reboot and the charger answers 401. That is what _authed is for, which
    is why the reboot poll does not log in on its own.
    """
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/login":
            return httpx.Response(200)
        if calls.count("/api/firmware") == 1:
            return httpx.Response(401)  # session died with the old connection
        return httpx.Response(
            200,
            json={
                "uploadInProgress": "false",
                "OD_fileFirmwareUpdateStatus": {"value": 10},
            },
        )

    with make_charger(handler) as ch:
        assert ch.firmware_status(timeout=4.0) == (False, 10)
    assert calls == ["/api/firmware", "/api/login", "/api/firmware"]


def test_reboot_poll_timeout_covers_the_retry_login(make_charger) -> None:
    """A poll's short budget must apply to the re-login it triggers too."""
    seen: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeout = request.extensions.get("timeout", {})
        seen.append(timeout.get("connect"))
        if request.url.path == "/api/login":
            return httpx.Response(200)
        if len(seen) == 1:
            return httpx.Response(401)
        return httpx.Response(200, json={})

    with make_charger(handler) as ch:
        ch.firmware_status(timeout=4.0)
    assert seen == [4.0, 4.0, 4.0]  # poll, re-login, retried poll


def test_default_requests_keep_the_client_timeout(make_charger) -> None:
    """Without an override, nothing narrows the ordinary 30 s/10 s budget."""
    seen: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout", {}).get("connect"))
        return httpx.Response(200, json={})

    with make_charger(handler) as ch:
        ch.firmware_status()
    assert seen == [CONNECT_TIMEOUT_S]


def test_properties_pagination_follows_local_offset(make_charger) -> None:
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offsets.append(int(request.url.params["offset"]))
        off = offsets[-1]
        end = min(off + 500, 537)
        items = [{"id": f"{0x1000 + i:X}_0", "value": i} for i in range(off, end)]
        return httpx.Response(200, json={"properties": items, "total": 537})

    with make_charger(handler) as ch:
        props = ch.properties("generic")
    assert offsets == [0, 500]
    assert len(props) == 537
    assert props[(0x1000, 0)] == 0
    assert props[(0x1000 + 536, 0)] == 536


def test_info_answers_from_the_unauthenticated_endpoint(make_charger) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "ObjectId": "ACE0781464",
                "Model": "NG910-60027",
                "Identity": "ACE0781464",
                "FWVersion": "7.4.5-4415",
                "Type": "2.0.1",
                "LastConfig": 123134,
                "SCNNetwork": "",
            },
        )

    with make_charger(handler) as ch:
        info = ch.basic_info()
    assert info.object_id == "ACE0781464"
    assert info.model == "NG910-60027"
    assert info.family == "NG"
    assert info.firmware_version == (7, 4, 5)
    assert info.sockets == 2  # "Type" counts them
    # No login, and no walk of the generic category.
    assert seen == ["/api/info"]


def test_basic_info_falls_back_when_the_endpoint_is_missing(make_charger) -> None:
    props = [
        {"id": "2050_0", "value": "NG910-60027"},
        {"id": "2051_0", "value": "ACE0781464"},
        {"id": "205E_0", "value": 1},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/info":
            return httpx.Response(404)
        return httpx.Response(200, json={"properties": props})

    with make_charger(handler) as ch:
        info = ch.basic_info()
    assert info.object_id == "ACE0781464"
    assert info.sockets == 1


def test_info_ignores_a_reply_that_is_not_the_document(make_charger) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not this charger's API</html>")

    with make_charger(handler) as ch:
        assert ch.info() is None


def test_basic_info_maps_properties(make_charger) -> None:
    props = [
        {"id": "1008_0", "value": "NG910"},
        {"id": "100A_0", "value": "7.4.5-4415"},
        {"id": "2050_0", "value": "NG910-60027"},
        {"id": "2051_0", "value": "ACE0781464"},
        {"id": "2053_0", "value": "ACE0781464"},
        {"id": "205E_0", "value": 1},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"properties": props})

    with make_charger(handler) as ch:
        info = ch.basic_info()
    assert info.object_id == "ACE0781464"
    assert info.model == "NG910-60027"
    assert info.family == "NG"
    assert info.firmware == "7.4.5-4415"
    assert info.firmware_version == (7, 4, 5)
    assert info.sockets == 1


def test_basic_info_model_falls_back_to_device_name() -> None:
    st = charger_mod.Station(
        ip="10.0.0.1", port=443, hostname="alfen-ace0781464.local."
    )
    ch = AlfenCharger(
        st,
        "admin",
        "pw",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"properties": [{"id": "1008_0", "value": "NG910"}]}
            )
        ),
    )
    with ch:
        info = ch.basic_info()
    assert info.model == "NG910"  # no sysChargePointModel -> device name
    assert info.object_id == "ace0781464"  # no serial property -> station fallback


def test_firmware_status_parsing(make_charger) -> None:
    body = (
        '{"version":2,"OD_fileFirmwareUpdateStatus":{"id":"2911_0","value":7},'
        ' "uploadInProgress": false}'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with make_charger(handler) as ch:
        assert ch.firmware_status() == (False, 7)


def test_firmware_status_tolerates_trailing_comma(make_charger) -> None:
    body = '{"OD_fileFirmwareUpdateStatus":{"id":"2911_0","value":10},}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with make_charger(handler) as ch:
        assert ch.firmware_status() == (False, 10)


def test_firmware_status_upload_in_progress_string(make_charger) -> None:
    body = '{"OD_fileFirmwareUpdateStatus":{"id":"2911_0","value":4},'
    body += ' "uploadInProgress": "true"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with make_charger(handler) as ch:
        assert ch.firmware_status() == (True, 4)


def test_firmware_status_empty_body(make_charger) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    with make_charger(handler) as ch:
        assert ch.firmware_status() == (False, 0)


def test_set_datetime_sends_date_command(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        ch.set_datetime()
        ch.set_datetime(is_ahp=True)
    # Like the app's SetDate: sysDateTime first, then tell the firmware.
    assert seen[0].url.path == "/api/prop"
    assert json.loads(seen[0].content)["2059_0"]["value"] > 1_700_000_000_000
    assert seen[1].url.path == "/api/cmd"
    assert json.loads(seen[1].content)["command"].startswith("date 20")
    assert seen[3].url.path == "/api/datetime"
    assert seen[3].content.startswith(b'"20')  # ISO-ish timestamp, JSON-quoted


def test_set_datetime_takes_an_explicit_moment(make_charger) -> None:
    from datetime import datetime, timezone

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    when = datetime(2026, 9, 4, 20, 31, 2, tzinfo=timezone.utc)
    with make_charger(handler) as ch:
        ch.set_datetime(when=when)
    assert json.loads(seen[0].content)["2059_0"]["value"] == 1788553862000
    assert json.loads(seen[1].content)["command"] == "date 2026-09-04 20:31:02"


def test_set_datetime_survives_a_charger_without_the_property(make_charger) -> None:
    """Old firmware refuses the property write; the command still goes."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        if request.url.path == "/api/prop" and request.method == "POST":
            return httpx.Response(404)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        ch.set_datetime()
    assert [r.url.path for r in seen][-1] == "/api/cmd"


def test_set_domain_item_hex_encodes_the_value(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        ch.set_domain_item(0, b"s3cret")
    assert seen[0].url.path == "/api/domain"
    assert json.loads(seen[0].content) == {
        "cmd": "add",
        "type": 0,
        "data": "733363726574",
    }


def test_set_password_posts_password(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        ch.set_password("hunter2")
    assert seen[0].url.path == "/api/password"
    assert json.loads(seen[0].content) == {"password": "hunter2"}


def test_fixed_chunk_stream_yields_small_chunks() -> None:
    body = b"x" * 17_000
    stream = _FixedChunkStream(body)
    pieces = list(stream)
    assert max(len(p) for p in pieces) <= UPLOAD_WRITE_SIZE
    assert b"".join(pieces) == body
    assert stream.sent == len(body)


def test_upload_firmware_builds_single_part(make_charger, monkeypatch) -> None:
    monkeypatch.setattr(charger_mod, "CONNECTION_RELEASE_PAUSE_S", 0.0)
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200)

    data = bytes(range(256)) * 40  # 10 240 B, spans several upload chunks
    with make_charger(handler) as ch:
        ch.upload_firmware(data)

    req = captured["request"]
    assert req.method == "POST"
    assert req.url.path == "/api/firmware"
    assert req.headers["accept"] == "*/*"  # JSON Accept would be rejected
    ct = req.headers["content-type"]
    assert ct.startswith("multipart/form-data; boundary=")
    boundary = ct.split("boundary=", 1)[1]
    # build_request() caches an empty body before the upload swaps in its stream,
    # so request.content would lie; consume the stream, as httpcore does.
    body = b"".join(req.stream)
    # Exactly one multipart part, framing byte-for-byte like the app's.
    assert body.count(b"Content-Disposition: form-data") == 1
    assert body.startswith(f"--{boundary}\r\n".encode())
    assert b'name="firmwarefile"; filename="filename"' in body
    assert b"Content-Type: application/octet-stream\r\n\r\n" in body
    assert body.endswith(f"\r\n--{boundary}--\r\n".encode())
    assert data in body
    assert req.headers["content-length"] == str(len(body))


def test_upload_firmware_retries_once_on_401(make_charger, monkeypatch) -> None:
    monkeypatch.setattr(charger_mod, "CONNECTION_RELEASE_PAUSE_S", 0.0)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/login":
            return httpx.Response(200)
        if calls.count("/api/firmware") == 1:
            return httpx.Response(401)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        ch.upload_firmware(b"IMAGE")
    assert calls == ["/api/login", "/api/firmware", "/api/login", "/api/firmware"]


def test_upload_firmware_rejected_raises(make_charger, monkeypatch) -> None:
    monkeypatch.setattr(charger_mod, "CONNECTION_RELEASE_PAUSE_S", 0.0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            return httpx.Response(200)
        return httpx.Response(400)

    with make_charger(handler) as ch:
        with pytest.raises(UploadError, match="HTTP 400"):
            ch.upload_firmware(b"IMAGE")


# --- Wi-Fi scan ------------------------------------------------------------------------------


def test_wifi_scan_gets_the_endpoint(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"scan_results": []})

    with make_charger(handler) as ch:
        body = ch.wifi_scan()
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/api/wifiscan"
    assert not seen[0].url.query
    assert json.loads(body) == {"scan_results": []}


# --- End-user (Eve Connect app) PIN -----------------------------------------------------------


def test_set_end_user_pin_posts_end_user_credentials(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        ch.set_end_user_pin("1234")
    assert seen[0].url.path == "/api/password"
    assert json.loads(seen[0].content) == {"username": "end user", "password": "1234"}


def test_disable_end_user_access_posts_reset(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        ch.disable_end_user_access()
    assert json.loads(seen[0].content) == {"username": "end user", "reset": True}


# --- OCPP charging profiles --------------------------------------------------------------------


def test_fetch_charging_profile_ids_gets_id_list(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="{}")

    with make_charger(handler) as ch:
        ch.fetch_charging_profile_ids()
    assert seen[0].method == "GET"
    assert str(seen[0].url).endswith("/api/chargingprofiles?id_list")


def test_fetch_charging_profile_gets_by_cpid(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="{}")

    with make_charger(handler) as ch:
        ch.fetch_charging_profile(-19061964)
    assert str(seen[0].url).endswith("/api/chargingprofiles?cpid=-19061964")


def test_clear_charging_profile_posts_empty_body(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        ch.clear_charging_profile("all")
    assert seen[0].method == "POST"
    assert str(seen[0].url).endswith("/api/chargingprofiles?clear=all")
    assert seen[0].content == b""


def test_add_charging_profile_posts_json_body(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    profile = {"connectorId": 0, "csChargingProfiles": {"chargingProfileId": 1}}
    with make_charger(handler) as ch:
        ch.add_charging_profile(profile)
    assert seen[0].method == "POST"
    assert str(seen[0].url).endswith("/api/chargingprofiles?add=")
    assert json.loads(seen[0].content) == profile


def test_fetch_charging_profile_ids_raises_on_404(make_charger) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with make_charger(handler) as ch:
        with pytest.raises(httpx.HTTPStatusError):
            ch.fetch_charging_profile_ids()


def test_set_datetime_stamps_the_command_when_it_is_sent(make_charger) -> None:
    """The command is stamped fresh, not from before the property write.

    The command is what actually moves the clock, and it leaves a whole
    round trip after the method was entered.  Stamping both from one reading
    left the charger that far behind for as long as it ran.
    """
    from datetime import datetime, timezone

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        if request.url.path == "/api/prop":
            time.sleep(1.2)  # a slow charger answering the property write
        return httpx.Response(200)

    entered = datetime.now(timezone.utc)
    with make_charger(handler) as ch:
        sent = ch.set_datetime()
    stamp = json.loads(seen[1].content)["command"].removeprefix("date ")
    assert stamp == sent.strftime("%Y-%m-%d %H:%M:%S")
    assert (sent - entered).total_seconds() >= 1.0


def test_debug_logging_redacts_secrets(make_charger, capsys) -> None:
    """Neither a password nor the recovery code reaches the debug log.

    ``reset_password`` sends the code under its own key, so a redaction that
    only knew ``password`` printed the one secret that gets an attacker in.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access": "tok", "refresh": "r"})

    station = Station(ip="10.0.0.1", port=443, https=True)
    ch = AlfenCharger(
        station,
        "admin",
        "hunter2",
        debug=True,
        transport=httpx.MockTransport(handler),
    )
    with ch:
        ch.login()
        ch.reset_password("RECOVERY-1234")

    err = capsys.readouterr().err
    assert "hunter2" not in err
    assert "RECOVERY-1234" not in err
    assert err.count('"***"') == 2
