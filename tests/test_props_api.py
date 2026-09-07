"""Tests for the live-property API additions in the charger client."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from alfenctl.charger import (
    parse_live_property,
    parse_prop_id,
)

Handler = Callable[[httpx.Request], httpx.Response]


def test_parse_live_property_full_entry() -> None:
    lp = parse_live_property(
        {
            "id": "2062_0",
            "access": 2,
            "type": 8,
            "len": 0,
            "cat": "generic",
            "value": 25.0,
        }
    )
    assert lp is not None
    assert lp.key == (0x2062, 0) and lp.value == 25.0
    assert lp.data_type == 8 and lp.access == 2 and lp.category == "generic"
    assert lp.writable


def test_parse_live_property_read_only_access_one() -> None:
    lp = parse_live_property({"id": "100A_0", "access": 1, "type": 9, "value": "7.4.5"})
    assert lp is not None and not lp.writable and lp.access == 1


def test_parse_live_property_bad_id_is_none() -> None:
    assert parse_live_property({"id": "zzz", "value": 1}) is None
    assert parse_live_property({"id": "2050", "value": 1}) is None  # no sub part


def test_fetch_properties_paginates_and_dedupes(make_charger) -> None:
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offsets.append(int(request.url.params["offset"]))
        off = offsets[-1]
        end = min(off + 500, 537)
        items = [
            {"id": f"{0x1000 + i:X}_0", "value": i, "type": 5, "access": 2}
            for i in range(off, end)
        ]
        return httpx.Response(200, json={"properties": items, "total": 537})

    with make_charger(handler) as ch:
        props = ch.fetch_properties()
    assert offsets == [0, 500]
    assert len(props) == 537
    assert props[0].key == (0x1000, 0)
    assert props[0].value == 0


def test_fetch_properties_query_order_matches_app(make_charger) -> None:
    """The charger matches the query prefix literally: cat= must precede limit=.

    With ``limit`` first the real NG910 returns ``{"properties": [],
    "total": 400}`` (ICULanDevice.UpdatePropertiesInternal always builds
    ``cat=<c>&limit=500`` and appends ``&offset=N``).
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"properties": [], "total": 0})

    with make_charger(handler) as ch:
        ch.fetch_properties("generic")
        ch.fetch_properties()
    assert seen[0].endswith("/api/prop?cat=generic&limit=500&offset=0")


def test_fetch_properties_by_ids_sends_ids_param(make_charger) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["ids"] == "2050_0,2062_0"
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "properties": [
                    {"id": "2050_0", "type": 9, "access": 2, "value": "NG910"},
                    {"id": "2062_0", "type": 8, "access": 2, "value": 25.0},
                ]
            },
        )

    with make_charger(handler) as ch:
        props = ch.fetch_properties_by_ids([(0x2050, 0), (0x2062, 0)])
    assert [(p.key, p.value) for p in props] == [
        ((0x2050, 0), "NG910"),
        ((0x2062, 0), 25.0),
    ]
    assert len(seen) == 1


def test_fetch_properties_by_ids_flat_map_shape(make_charger) -> None:
    """Some firmware answers ids= reads with a flat {id: value} map."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"2050_0": "NG910", "version": 2})

    with make_charger(handler) as ch:
        props = ch.fetch_properties_by_ids([(0x2050, 0)])
    assert len(props) == 1 and props[0].value == "NG910"


def test_all_properties_walks_categories(make_charger) -> None:
    cats: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/categories":
            return httpx.Response(200, json={"categories": ["generic", "ocpp"]})
        cat = request.url.params.get("cat")
        cats.append(str(cat))
        if cat == "generic":
            return httpx.Response(
                200,
                json={
                    "properties": [
                        {"id": "2050_0", "type": 9, "access": 2, "value": "NG910"}
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "properties": [{"id": "2062_0", "type": 8, "access": 2, "value": 25.0}]
            },
        )

    with make_charger(handler) as ch:
        props = ch.all_properties()
    assert cats == ["generic", "ocpp"]
    assert {p.key for p in props} == {(0x2050, 0), (0x2062, 0)}


def test_all_properties_fallback_without_categories(make_charger) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/categories":
            return httpx.Response(200, json={"categories": []})
        assert "cat" not in request.url.params  # unfiltered AHP-style read
        return httpx.Response(
            200,
            json={
                "properties": [{"id": "2050_0", "type": 9, "access": 2, "value": "x"}]
            },
        )

    with make_charger(handler) as ch:
        props = ch.all_properties()
    assert len(props) == 1


def test_write_properties_batches_of_15(make_charger) -> None:
    posts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(httpx.Response(200, json={}).json() if False else None)
        import json as _json

        posts[-1] = _json.loads(request.content)
        return httpx.Response(200)

    writes = {
        (0x2000 + i, 0): (i, 5) for i in range(16)
    }  # 16 entries -> one batch of 15 + one of 1
    with make_charger(handler) as ch:
        ch.write_properties(writes)
    assert len(posts) == 2
    assert len(posts[0]) == 15 and len(posts[1]) == 1
    entry = posts[0]["2000_0"]
    assert entry == {"id": "2000_0", "value": 0}


def test_write_properties_encodes_per_type(make_charger) -> None:
    import json as _json

    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(_json.loads(request.content))
        return httpx.Response(200)

    with make_charger(handler) as ch:
        ch.write_properties(
            {
                (0x2062, 0): (25.5, 8),
                (0x2050, 0): ("TWIN", 9),
                (0x64, 0): (b"\x0a\xff", 64),
            }
        )
    body = bodies[0]
    assert body["2062_0"] == {"id": "2062_0", "value": 25.5}
    assert body["2050_0"] == {"id": "2050_0", "value": "TWIN"}
    assert body["64_0"] == {"id": "64_0", "value": "0A,FF"}


def test_properties_dict_wrapper_keeps_contract(make_charger) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"properties": [{"id": "2050_0", "value": "NG910"}]},
        )

    with make_charger(handler) as ch:
        props = ch.properties("generic")
    assert props == {(0x2050, 0): "NG910"}


def test_parse_prop_id_widths() -> None:
    assert parse_prop_id("2221_A") == (0x2221, 0xA)
    assert parse_prop_id("2221_0A") == (0x2221, 0xA)
