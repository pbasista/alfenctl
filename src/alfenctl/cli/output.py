"""Printing the shapes that are alfenctl's own.

Tables, prompts, JSON and the clock format are
:mod:`devicectl.cli.output` and are re-exported here, so a command imports
one module rather than two.  What is here is what only a charger has: a
property row, and the note that says a write will not take until a restart.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import Any

from devicectl.cli.output import (
    CLOCK_FORMAT,
    aborted,
    collect_json,
    confirm,
    error,
    may_overwrite,
    note,
    print_json,
    print_rows,
    print_table,
    read_in,
    render_json,
    shorten,
    stop_collecting,
    warn,
    write_out,
)

from alfenctl.values import Property, format_value, reboot_required


def note_reboot_required(keys: Iterable[tuple[int, int]]) -> None:
    """Say which of these writes the charger will not act on until it restarts.

    The charger answers 200 to every one of them and carries on as before, so
    a command that writes one and says nothing is a command that looks like it
    worked.  Printed to stderr, so a script's own output is not disturbed.
    """
    pending = reboot_required(keys)
    if not pending:
        return
    names = ", ".join(f"{p:04X}_{s:X}" for p, s in sorted(pending))
    print(
        f"note: {names} takes effect only after a restart; run: alfenctl reboot",
        file=sys.stderr,
    )


def property_row(p: Property) -> list[str]:
    """Return the human-table row for a property."""
    # A `?` rather than a blank: a blank cell could be a title nobody
    # filled in, and this is a register nobody -- not the EDS, not the
    # vendor's own apps -- has ever named.
    return [p.id_str, p.name, format_value(p), p.access_label, p.title or "?"]


PROPERTY_HEADERS = ["ID", "NAME", "VALUE", "ACCESS", "TITLE"]


def property_json(p: Property) -> dict[str, Any]:
    """Return the JSON form of a property (full metadata, unlike the table)."""
    doc: dict[str, Any] = {"id": p.id_str, "name": p.name, "value": p.value}
    if p.title:
        doc["title"] = p.title
    # `known` says whether that title came from anywhere: false is the
    # marker for a property whose purpose no source describes.
    doc["known"] = p.known
    doc["type"] = p.type_name
    doc["access"] = p.access_label
    if p.category:
        doc["category"] = p.category
    if p.length is not None:
        doc["length"] = p.length
    if p.unit:
        doc["unit"] = p.unit
    return doc


def print_properties(props: list[Property], *, as_json: bool) -> None:
    """Print properties as the human table or as JSON."""
    if as_json:
        print_json([property_json(p) for p in props])
    else:
        print_table(PROPERTY_HEADERS, [property_row(p) for p in props])


__all__ = [
    "CLOCK_FORMAT",
    "PROPERTY_HEADERS",
    "aborted",
    "collect_json",
    "confirm",
    "error",
    "may_overwrite",
    "note",
    "note_reboot_required",
    "print_json",
    "print_properties",
    "print_rows",
    "print_table",
    "property_json",
    "read_in",
    "property_row",
    "render_json",
    "shorten",
    "stop_collecting",
    "warn",
    "write_out",
]
