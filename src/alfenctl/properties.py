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
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from fnmatch import fnmatch

from alfenctl.charger import AlfenCharger
from alfenctl.eds import PropertyCatalog, PropertyDef, parse_id_query
from alfenctl.values import Property, merge


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
