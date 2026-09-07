"""Tests for the RFID whitelist: sparse paging, tag records and import files."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from alfenctl import whitelist as wl

# 2027-01-01 00:00:00 UTC, as the charger sends it (Unix seconds).
EXPIRY_EPOCH = int(datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp())


def page(*items: dict) -> str:
    """Render a /api/whitelist page the way the charger does."""
    return json.dumps({"version": 1, "whitelist": list(items)})


def entry(tag: str, **over) -> dict:
    base = {"tag": tag, "parent": "", "status": 1, "expiryDate": "0"}
    base.update(over)
    return base


class FakeList:
    """A charger whitelist that is *sparse*, like the real one."""

    def __init__(self, at: dict[int, list[dict]]) -> None:
        self.at = at  # index -> entries served there
        self.indexes: list[int] = []
        self.verbs: list[str] = []
        self.records: list[dict] = []

    def fetch_whitelist(self, index: int = 0) -> str:
        self.indexes.append(index)
        return page(*self.at.get(index, []))

    def whitelist_verb(self, query: str) -> None:
        self.verbs.append(query)

    def add_tag(self, record: dict) -> None:
        self.records.append(dict(record))


# --- Parsing -----------------------------------------------------------------------------


def test_parse_tag_reads_every_field() -> None:
    tag = wl.parse_tag(
        entry("04A1B2C3", parent="04FFFFFF", status=2, expiryDate=str(EXPIRY_EPOCH))
    )
    assert tag is not None
    assert tag.tag == "04A1B2C3"
    assert tag.parent == "04FFFFFF"
    assert tag.status_name == "blocked"
    assert tag.expires is not None
    assert tag.expires.astimezone(timezone.utc).year == 2027


def test_zero_expiry_means_no_expiry() -> None:
    """The charger sends 0 for a tag that never expires."""
    tag = wl.parse_tag(entry("04A1B2C3", expiryDate="0"))
    assert tag.expires is None
    assert tag.expiry_text == "<no expiry date>"


def test_parse_tag_rejects_an_entry_with_no_id() -> None:
    assert wl.parse_tag(entry("")) is None


def test_parse_tag_survives_a_bad_status_or_expiry() -> None:
    tag = wl.parse_tag({"tag": "04AA", "status": "?", "expiryDate": "later"})
    assert tag.status == wl.STATUS_UNKNOWN and tag.expires is None


def test_unknown_status_code_keeps_its_number() -> None:
    assert wl.parse_tag(entry("04AA", status=42)).status_name == "42"


def test_master_card_status() -> None:
    assert wl.parse_tag(entry("04AA", status=99)).status_name == "master"


def test_parse_page_tolerates_junk() -> None:
    assert wl.parse_page("") == []
    assert wl.parse_page("not json") == []
    assert wl.parse_page('{"version":1}') == []


# --- Sparse paging -----------------------------------------------------------------------


def test_download_reads_a_dense_list() -> None:
    source = FakeList({0: [entry("04AA"), entry("04BB")], 2: [entry("04CC")]})
    tags = wl.download(source)
    assert [t.tag for t in tags] == ["04AA", "04BB", "04CC"]


def test_download_steps_over_a_gap() -> None:
    """An empty page is not the end: the list is sparse."""
    source = FakeList({0: [entry("04AA")], 17: [entry("04BB")]})
    tags = wl.download(source, stride=wl.PROBE_STRIDE)
    assert [t.tag for t in tags] == ["04AA", "04BB"]
    assert 17 in source.indexes


def test_download_gives_up_after_a_long_empty_run() -> None:
    source = FakeList({0: [entry("04AA")]})
    tags = wl.download(source, stride=wl.PROBE_STRIDE)
    assert [t.tag for t in tags] == ["04AA"]
    # Probed forward in strides, then stopped rather than walking to MAX_TAGS.
    assert max(source.indexes) <= 1 + wl.MAX_EMPTY_PROBE + wl.PROBE_STRIDE


def test_download_on_an_empty_whitelist() -> None:
    assert wl.download(FakeList({})) == []


def test_probe_stride_follows_the_firmware() -> None:
    assert wl.probe_stride((3, 4, 0)) == wl.PROBE_STRIDE
    assert wl.probe_stride((3, 3, 9)) == wl.PROBE_STRIDE_OLD_FIRMWARE
    assert wl.probe_stride(None) == wl.PROBE_STRIDE


# --- Verbs -------------------------------------------------------------------------------


def test_verbs_use_the_query_form() -> None:
    source = FakeList({})
    wl.add(source, "04AA")
    wl.remove(source, "04BB")
    wl.clear(source)
    wl.start_add_mode(source)
    assert source.verbs == ["add=04AA", "remove=04BB", "clear", "starttagaddmode"]


def test_upsert_sends_a_whole_record() -> None:
    source = FakeList({})
    wl.upsert(
        source,
        "04AA",
        parent="04FF",
        status=wl.STATUS_BLOCKED,
        expires=datetime(2027, 1, 1),
    )
    assert source.records == [
        {"tagid": "04AA", "parentid": "04FF", "status": 2, "expire": "2027-01-01"}
    ]


def test_upsert_without_an_expiry_sends_the_apps_sentinel() -> None:
    source = FakeList({})
    wl.upsert(source, "04AA")
    assert source.records[0]["expire"] == wl.NO_EXPIRY


# --- Import files ------------------------------------------------------------------------


def test_parse_tag_file_accepts_a_bare_list_of_ids() -> None:
    tags = wl.parse_tag_file("04AA\n04BB  # a comment\n\n# whole-line comment\n")
    assert [t.tag for t in tags] == ["04AA", "04BB"]
    assert all(t.status == wl.STATUS_ACTIVE for t in tags)


def test_parse_tag_file_accepts_csv_with_a_header() -> None:
    text = "tag,parent,status,expires\n04AA,04FF,blocked,2027-01-01\n"
    tags = wl.parse_tag_file(text)
    assert len(tags) == 1
    assert tags[0].parent == "04FF"
    assert tags[0].status == wl.STATUS_BLOCKED
    assert tags[0].expires == datetime(2027, 1, 1)


def test_parse_tag_file_accepts_json() -> None:
    text = json.dumps([{"tag": "04AA", "status": "master"}, "04BB"])
    tags = wl.parse_tag_file(text)
    assert [t.tag for t in tags] == ["04AA", "04BB"]
    assert tags[0].status == wl.STATUS_MASTER


def test_tag_dict_round_trips_through_parse() -> None:
    tag = wl.Tag(
        "04AA", parent="04FF", status=wl.STATUS_BLOCKED, expires=datetime(2027, 1, 1)
    )
    again = wl.parse_import_entry(wl.tag_dict(tag))
    assert (again.tag, again.parent, again.status, again.expires) == (
        tag.tag,
        tag.parent,
        tag.status,
        tag.expires,
    )


# --- Diff --------------------------------------------------------------------------------


def test_diff_adds_updates_and_removes() -> None:
    current = [
        wl.Tag("04AA", status=wl.STATUS_ACTIVE),
        wl.Tag("04BB", status=wl.STATUS_ACTIVE),
    ]
    wanted = [
        wl.Tag("04AA", status=wl.STATUS_ACTIVE),  # unchanged
        wl.Tag("04BB", status=wl.STATUS_BLOCKED),  # changed
        wl.Tag("04CC", status=wl.STATUS_ACTIVE),  # new
    ]
    writes, removals = wl.diff(current, wanted)
    assert sorted(t.tag for t in writes) == ["04BB", "04CC"]
    assert removals == []


def test_diff_reports_what_the_file_leaves_out() -> None:
    writes, removals = wl.diff([wl.Tag("04AA")], [wl.Tag("04BB")])
    assert [t.tag for t in writes] == ["04BB"]
    assert [t.tag for t in removals] == ["04AA"]


@pytest.mark.parametrize(
    "changed",
    [
        wl.Tag("04AA", parent="04FF"),
        wl.Tag("04AA", expires=datetime(2027, 1, 1)),
        wl.Tag("04AA", status=wl.STATUS_BLOCKED),
    ],
)
def test_diff_notices_every_field(changed: wl.Tag) -> None:
    writes, _ = wl.diff([wl.Tag("04AA", status=wl.STATUS_ACTIVE)], [changed])
    assert len(writes) == 1
