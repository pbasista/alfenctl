"""The charger's local RFID whitelist: which tags may start a session.

The whitelist is the charger's own authorization list, consulted when it
cannot (or is configured not to) ask a backoffice.  ``GET
/api/whitelist?index=N`` returns a page of it as JSON
(``{"version": 1, "whitelist": [...]}``), and the rest of the endpoint is
verbs: ``?add=<tag>``, ``?remove=<tag>``, ``?clear``, and
``?starttagaddmode``, which enrols whatever tag is next presented at the
reader.  ``POST /api/addtag`` writes a whole record -- parent tag, status
and expiry -- in one go (``ICUWhiteList``).

Paging is unusual and worth knowing about: the charger answers
``index=N`` with the tags *at* that index, and an empty page does not mean
the end.  The list is sparse, so the app steps the index forward in
16-tag strides (15 below firmware 3.4.0) through up to 128 empty slots
before it accepts that the list has ended -- which is what
:func:`download` does here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol

from alfenctl.values import as_int

# ICUTagStatus
STATUS_UNKNOWN = 0
STATUS_ACTIVE = 1
STATUS_BLOCKED = 2
STATUS_DELETED = 3
STATUS_MASTER = 99
TAG_STATUSES = {
    STATUS_UNKNOWN: "unknown",
    STATUS_ACTIVE: "active",
    STATUS_BLOCKED: "blocked",
    STATUS_DELETED: "deleted",
    STATUS_MASTER: "master",
}
STATUS_CODES = {name: code for code, name in TAG_STATUSES.items()}

# How far the app probes past the last tag it saw before calling it the end,
# and the stride it probes with (ICUWhiteList.DoWorkRead).
PROBE_STRIDE = 16
PROBE_STRIDE_OLD_FIRMWARE = 15
OLD_FIRMWARE_FLOOR = (3, 4, 0)
MAX_EMPTY_PROBE = 128
# The app's own ceiling on how many tags it will read (ICUWhiteList ctor).
MAX_TAGS = 10000

# The app writes this date when a tag has no expiry (PanelAuthorization).
NO_EXPIRY = "1970-01-01"
EXPIRY_FORMAT = "%Y-%m-%d"


class _Source(Protocol):
    """The charger calls this module needs."""

    def fetch_whitelist(self, index: int = 0) -> str: ...
    def whitelist_verb(self, query: str) -> None: ...
    def add_tag(self, record: dict[str, object]) -> None: ...


@dataclass
class Tag:
    """One whitelist entry."""

    tag: str
    parent: str = ""
    status: int = STATUS_UNKNOWN
    expires: datetime | None = None

    @property
    def status_name(self) -> str:
        """The status as a word, or the raw code if the firmware invented one."""
        return TAG_STATUSES.get(self.status, str(self.status))

    @property
    def expiry_text(self) -> str:
        """The expiry date, or the app's ``<no expiry date>``."""
        return (
            self.expires.strftime(EXPIRY_FORMAT) if self.expires else "<no expiry date>"
        )


def parse_tag(item: dict[str, object]) -> Tag | None:
    """Parse one whitelist entry, or None when it carries no tag id.

    ``expiryDate`` is a Unix timestamp in seconds; the app treats 0 (and an
    unparseable value) as "no expiry" (``ICUWhitelistItem``).
    """
    tag = str(item.get("tag", "")).strip()
    if not tag:
        return None
    status = as_int(item.get("status"))
    if status is None:
        status = STATUS_UNKNOWN
    expires: datetime | None = None
    try:
        seconds = int(str(item.get("expiryDate", "0")))
    except (TypeError, ValueError):
        seconds = 0
    if seconds:
        expires = datetime.fromtimestamp(seconds, timezone.utc).astimezone()
    return Tag(
        tag=tag,
        parent=str(item.get("parent", "") or ""),
        status=status,
        expires=expires,
    )


def parse_page(body: str) -> list[Tag]:
    """Parse one ``/api/whitelist`` page into tags."""
    try:
        doc = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        return []
    entries = doc.get("whitelist") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        return []
    return [t for t in (parse_tag(e) for e in entries if isinstance(e, dict)) if t]


def probe_stride(firmware_version: tuple[int, int, int] | None) -> int:
    """Return the index stride to probe the sparse list with."""
    if firmware_version is not None and firmware_version < OLD_FIRMWARE_FLOOR:
        return PROBE_STRIDE_OLD_FIRMWARE
    return PROBE_STRIDE


def download(
    source: _Source,
    *,
    stride: int = PROBE_STRIDE,
    max_tags: int = MAX_TAGS,
    on_progress: Callable[[int], None] | None = None,
) -> list[Tag]:
    """Read the whole whitelist, walking past the gaps in it.

    Mirrors ``ICUWhiteList.DoWorkRead``: ask at the index just past what we
    have, and when a page comes back empty step the index on by ``stride``
    rather than stopping -- the list is sparse.  Only after
    :data:`MAX_EMPTY_PROBE` of empty probing is it really the end.
    """
    tags: list[Tag] = []
    seen: set[str] = set()
    empty_span = 0
    while len(tags) < max_tags:
        index = len(tags) + empty_span
        if on_progress is not None:
            on_progress(len(tags))
        fresh = [
            t for t in parse_page(source.fetch_whitelist(index)) if t.tag not in seen
        ]
        if not fresh:
            if empty_span > MAX_EMPTY_PROBE or index + empty_span >= max_tags:
                break
            empty_span += stride
            continue
        seen.update(t.tag for t in fresh)
        tags.extend(fresh)
    return tags


def add(source: _Source, tag: str) -> None:
    """Add a tag with the charger's defaults (``whitelist?add=``)."""
    source.whitelist_verb(f"add={tag}")


def remove(source: _Source, tag: str) -> None:
    """Remove one tag (``whitelist?remove=``)."""
    source.whitelist_verb(f"remove={tag}")


def clear(source: _Source) -> None:
    """Remove every tag (``whitelist?clear``)."""
    source.whitelist_verb("clear")


def start_add_mode(source: _Source) -> None:
    """Enrol the next tag presented at the reader (``whitelist?starttagaddmode``)."""
    source.whitelist_verb("starttagaddmode")


def upsert(
    source: _Source,
    tag: str,
    *,
    parent: str = "",
    status: int = STATUS_ACTIVE,
    expires: datetime | None = None,
) -> None:
    """Write a whole tag record (``POST /api/addtag``), adding or updating it.

    The expiry goes over as ``yyyy-MM-dd``; the app sends 1970-01-01 to mean
    "no expiry" (``PanelAuthorization.s_sNoExpiryDate``).
    """
    source.add_tag(
        {
            "tagid": tag,
            "parentid": parent,
            "status": status,
            "expire": expires.strftime(EXPIRY_FORMAT) if expires else NO_EXPIRY,
        }
    )


# --- Files -------------------------------------------------------------------------------

TAG_COLUMNS = ("tag", "parent", "status", "expires")


def tag_row(tag: Tag) -> list[str]:
    """Return one :data:`TAG_COLUMNS` row for ``tag``."""
    return [
        tag.tag,
        tag.parent,
        tag.status_name,
        tag.expires.strftime(EXPIRY_FORMAT) if tag.expires else "",
    ]


def parse_tag_file(text: str) -> list[Tag]:
    """Parse a tag list for import: JSON from ``tags list --json``, or CSV/plain.

    A plain list of tag ids, one per line, is accepted too -- it is what
    anyone with a spreadsheet of cards will have.  ``#`` starts a comment.
    """
    stripped = text.strip()
    if stripped.startswith("["):
        doc = json.loads(stripped)
        return [t for t in (parse_import_entry(e) for e in doc) if t]
    out: list[Tag] = []
    for line in stripped.splitlines():
        row = line.split("#", 1)[0].strip()
        if not row or row.lower().startswith("tag,"):  # blank, comment, CSV header
            continue
        fields = [f.strip() for f in row.split(",")]
        entry: dict[str, object] = {"tag": fields[0]}
        for name, value in zip(TAG_COLUMNS[1:], fields[1:]):
            if value:
                entry[name] = value
        if tag := parse_import_entry(entry):
            out.append(tag)
    return out


def parse_import_entry(entry: object) -> Tag | None:
    """Parse one entry of an import file (a dict, or a bare tag id string)."""
    if isinstance(entry, str):
        return Tag(tag=entry.strip()) if entry.strip() else None
    if not isinstance(entry, dict):
        return None
    tag = str(entry.get("tag") or entry.get("tagid") or "").strip()
    if not tag:
        return None
    raw_status = entry.get("status", STATUS_ACTIVE)
    if isinstance(raw_status, str):
        status = STATUS_CODES.get(raw_status.strip().lower())
        if status is None:
            try:
                status = int(raw_status)
            except ValueError:
                status = STATUS_ACTIVE
    else:
        status = int(raw_status)
    expires: datetime | None = None
    raw_expiry = str(entry.get("expires") or entry.get("expire") or "").strip()
    if raw_expiry and raw_expiry != NO_EXPIRY:
        try:
            expires = datetime.strptime(raw_expiry[:10], EXPIRY_FORMAT)
        except ValueError:
            expires = None
    return Tag(
        tag=tag,
        parent=str(entry.get("parent") or entry.get("parentid") or ""),
        status=status,
        expires=expires,
    )


def tag_dict(tag: Tag) -> dict[str, object]:
    """Return ``tag`` as a JSON-ready dict (the shape :func:`parse_tag_file` reads)."""
    out: dict[str, object] = {
        "tag": tag.tag,
        "status": tag.status_name,
    }
    if tag.parent:
        out["parent"] = tag.parent
    if tag.expires:
        out["expires"] = tag.expires.strftime(EXPIRY_FORMAT)
    return out


def diff(current: Iterable[Tag], wanted: Iterable[Tag]) -> tuple[list[Tag], list[Tag]]:
    """Return ``(to write, to remove)`` to make ``current`` match ``wanted``."""
    have = {t.tag: t for t in current}
    want = {t.tag: t for t in wanted}
    writes = [
        t
        for name, t in want.items()
        if name not in have
        or (have[name].status, have[name].parent, have[name].expires)
        != (t.status, t.parent, t.expires)
    ]
    removals = [t for name, t in have.items() if name not in want]
    return writes, removals
