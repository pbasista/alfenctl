"""Turning what the user asked for into properties the charger answered with.

Two ways in.  :func:`resolve` takes explicit queries -- ids like ``2060_0``
or catalog names like ``ocppBootNotificationVendor`` -- and reads exactly
those.  :func:`collect` walks everything the charger will list, optionally
one category at a time, and filters afterwards.

Both merge two sources: the live reply, which is the authority on what a
property *is* right now, and the bundled EDS catalog, which is the
authority on what it *means*.  Either can be missing -- the charger answers
for about three times as many properties as the EDS describes, and the EDS
describes some the charger does not have -- so :func:`alfenctl.values.merge`
takes both as optional.

On top of them sits :func:`plan_import`, which is what "apply this settings
file" means before anything is written: read what the file names, coerce
each value the way that property is encoded, and sort the result into what
will change, what cannot be written, what belongs to the charger it came
from, and what could not be read at all.  It answers rather than prints, so
the terminal and the browser show the same four lists; they had been three
separate diffs, and the two in the web layer quietly dropped the read-only
and device-bound reporting the CLI does.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any

from alfenctl.charger import AlfenCharger
from alfenctl.eds import PropertyCatalog, PropertyDef, parse_id_query
from alfenctl.values import Property, coerce_input, is_portable, merge, values_equal


def resolve(
    charger: AlfenCharger, catalog: PropertyCatalog, queries: Sequence[str]
) -> tuple[list[Property], list[str]]:
    """Resolve id/name queries into merged properties, fetching live state.

    Returns the properties plus human-readable errors for queries that
    resolved to nothing.  An id query is sent to the charger even when the
    catalog doesn't know it (the charger is the source of truth); a name
    query must match the catalog.
    """
    keys: list[tuple[int, int]] = []
    defs: dict[tuple[int, int], PropertyDef] = {}
    errors: list[str] = []
    for q in queries:
        key = parse_id_query(q)
        if key is not None:
            keys.append(key)
            d = catalog.get(key)
            if d is not None:
                defs[key] = d
        else:
            matches = catalog.get_by_name(q)
            if not matches:
                errors.append(f"no property named '{q}'")
                continue
            for d in matches:
                keys.append((d.prop_id, d.sub_id))
                defs[(d.prop_id, d.sub_id)] = d
    live = {lp.key: lp for lp in charger.fetch_properties_by_ids(keys)} if keys else {}
    props: list[Property] = []
    for key in keys:
        d = defs.get(key)
        lp = live.get(key)
        if lp is None and d is None:
            errors.append(f"property {key[0]:X}_{key[1]:X} not found on the charger")
            continue
        props.append(merge(lp, d))
    return props, errors


def collect(
    charger: AlfenCharger,
    catalog: PropertyCatalog,
    pattern: str | None = None,
    category: str | None = None,
    on_category: Callable[[int, int, str], None] | None = None,
) -> list[Property]:
    """Fetch live properties (all or one category) merged with the catalog.

    The license properties (21A0_0/21A1_0/21A2_0) are only reachable via
    explicit ``ids=`` reads, so they are fetched and merged on top of the
    whole-charger walk -- otherwise backups would silently lose them.  A
    one-category read does not get them: they belong to no category, and a
    row that turned up under every category the browser asked for would be
    saying the opposite.
    """
    from alfenctl.license import PROP_FEATURES, PROP_LICENSE_KEY, PROP_UNIQUE_ID

    live = (
        charger.fetch_properties(category)
        if category
        else charger.all_properties(on_category)
    )

    props = [merge(lp, catalog.get(lp.key)) for lp in live]
    if not category:
        hidden = {
            lp.key: lp
            for lp in charger.fetch_properties_by_ids(
                [PROP_UNIQUE_ID, PROP_LICENSE_KEY, PROP_FEATURES]
            )
        }
        for key, lp in hidden.items():
            if key not in {p.key for p in props}:
                props.append(merge(lp, catalog.get(key)))
    if pattern:
        props = [p for p in props if matches(p, pattern)]
    return sorted(props, key=lambda p: p.key)


def matches(p: Property, pattern: str) -> bool:
    """Case-insensitive glob against id, name and title."""
    pat = pattern.lower()
    return (
        fnmatch(p.id_str.lower(), pat)
        or fnmatch(p.name.lower(), pat)
        or fnmatch(p.title.lower(), pat)
    )


__all__ = ["collect", "matches", "resolve"]


# --- applying a settings file --------------------------------------------------------------

# What the import file itself has to look like, said once: the app's own XML
# (encrypted or not), or the JSON `alfenctl export` writes.  The format is
# recognised from the content rather than the name, so a settings file saved
# under any extension still loads.
ENTRIES_EXPECTED = 'expected a JSON array of {"id", "value"} entries'


def parse_entries(text: str) -> list[dict[str, Any]]:
    """Read a settings file into ``{"id", "value"}`` entries.

    Raises :class:`ValueError` -- which ``json`` raises a subclass of -- for
    anything that is neither format.
    """
    from alfenctl import settings

    if text.lstrip().startswith("<") or settings.looks_encrypted(text):
        return list(settings.parse(text).as_entries())
    data = json.loads(text)
    if not isinstance(data, list) or not all(
        isinstance(e, dict) and "id" in e and "value" in e for e in data
    ):
        raise ValueError(ENTRIES_EXPECTED)
    return data


@dataclass(frozen=True)
class Change:
    """One property the file would change, with the value it would be given."""

    prop: Property
    value: Any
    """The coerced value, ready to write; ``prop.value`` is what is there now."""

    @property
    def before(self) -> str:
        """What the charger holds now, as it would be printed."""
        return self.prop.encoded(self.prop.value)

    @property
    def after(self) -> str:
        """What the file would put there, as it would be printed."""
        return self.prop.encoded(self.value)


@dataclass
class ImportPlan:
    """What applying a settings file to this charger would do, and would not.

    Four ways a named property can fail to be written, kept apart because
    they mean different things to whoever asked: the charger will not take it
    (:attr:`read_only`), it identifies the charger the file came from
    (:attr:`bound`), the value is not one that property can hold
    (:attr:`invalid`), or this charger does not have it at all
    (:attr:`missing`).
    """

    changes: list[Change] = field(default_factory=list)
    read_only: list[Property] = field(default_factory=list)
    bound: list[Property] = field(default_factory=list)
    invalid: list[tuple[str, str]] = field(default_factory=list)
    """``(id, why)`` for a value that would not coerce."""

    missing: list[str] = field(default_factory=list)
    """What :func:`resolve` could not find, in its own words."""

    @property
    def writes(self) -> dict[tuple[int, int], tuple[Any, int | None]]:
        """The changes as one batch for :meth:`AlfenCharger.write_properties`."""
        return {c.prop.key: (c.value, c.prop.data_type) for c in self.changes}

    def __bool__(self) -> bool:
        """Whether there is anything to write."""
        return bool(self.changes)


def plan_import(
    charger: AlfenCharger,
    catalog: PropertyCatalog,
    entries: Sequence[dict[str, Any]],
    *,
    force: bool = False,
) -> ImportPlan:
    """Work out what applying ``entries`` to this charger would change.

    Nothing is written: the caller previews, asks, and then hands
    :attr:`ImportPlan.writes` to the charger in one batch.

    ``force`` writes the properties that belong to the charger a file came
    from -- serial, identity, MAC, IP, SCN membership, licence key, meter
    wiring.  Without it they are collected in :attr:`ImportPlan.bound`, and
    only when they actually differ: a file that happens to carry this
    charger's own serial has not asked for anything.
    """
    props, errors = resolve(charger, catalog, [str(e["id"]) for e in entries])
    by_id = {p.id_str: p for p in props}
    plan = ImportPlan(missing=list(errors))
    for entry in entries:
        prop = by_id.get(str(entry["id"]))
        if prop is None:
            continue
        if not prop.writable:
            plan.read_only.append(prop)
            continue
        try:
            value = coerce_input(prop, entry["value"])
        except ValueError as exc:
            plan.invalid.append((prop.id_str, str(exc)))
            continue
        if values_equal(prop, value):
            continue  # already in the desired state
        if not force and not is_portable(prop.key):
            plan.bound.append(prop)
            continue
        plan.changes.append(Change(prop=prop, value=value))
    return plan
