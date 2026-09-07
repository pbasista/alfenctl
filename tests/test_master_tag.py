"""Tests for the master-tag module, driven through httpx's MockTransport."""

from __future__ import annotations

import json

import httpx

from alfenctl import master_tag


def test_read_reports_unsupported_when_charger_answers_neither_property(
    make_charger,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"properties": []})

    with make_charger(handler) as ch:
        state = master_tag.read(ch)
    assert not state.supported
    assert not state.enabled
    assert state.tag == ""


def test_read_parses_enabled_and_tag(make_charger) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/prop"
        return httpx.Response(
            200,
            json={
                "properties": [
                    {"id": "2400_1", "value": 1},
                    {"id": "2400_2", "value": "04A1B2C3D4E5"},
                ]
            },
        )

    with make_charger(handler) as ch:
        state = master_tag.read(ch)
    assert state.supported
    assert state.enabled
    assert state.tag == "04A1B2C3D4E5"


def test_read_disabled_mode(make_charger) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "properties": [
                    {"id": "2400_1", "value": 0},
                    {"id": "2400_2", "value": "04A1B2C3D4E5"},
                ]
            },
        )

    with make_charger(handler) as ch:
        state = master_tag.read(ch)
    assert state.supported
    assert not state.enabled


def test_set_tag_writes_both_properties(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        master_tag.set_tag(ch, "04A1B2C3D4E5")
    body = json.loads(seen[0].content)
    assert body["2400_2"]["value"] == "04A1B2C3D4E5"
    assert body["2400_1"]["value"] == 1


def test_set_tag_disabled(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        master_tag.set_tag(ch, "04A1B2C3D4E5", enabled=False)
    body = json.loads(seen[0].content)
    assert body["2400_1"]["value"] == 0


def test_clear_only_writes_the_tag_property(make_charger) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200)

    with make_charger(handler) as ch:
        master_tag.clear(ch)
    body = json.loads(seen[0].content)
    assert list(body.keys()) == ["2400_2"]
    assert body["2400_2"]["value"] == ""
