"""Printing: tables, property rows, the one timestamp format, the one prompt.

Every command that shows something goes through here, so column widths,
JSON shape and clock formatting stay the same across thirty commands
without each one deciding for itself.  :func:`confirm` is here for the same
reason: a dozen commands ask before doing something irreversible, and they
should all ask it the same way.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from typing import Any

from alfenctl.values import Property, format_value, reboot_required

# How clock readings are printed: seconds matter, sub-seconds do not.
CLOCK_FORMAT = "%Y-%m-%d %H:%M:%S"


def confirm(question: str) -> bool:
    """Ask a yes/no question; anything but an explicit yes is a no.

    End-of-file counts as a no, so a command left to run unattended stops
    rather than raising at the prompt.  Every command that asks also takes
    ``-y`` to skip the question; declining exits non-zero, because nothing
    that was asked for was done.
    """
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    """Print a left-aligned table with columns sized to their widest cell."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip())
    for row in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip())


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


def print_rows(title: str, rows: list[tuple[str, str]]) -> None:
    """Print a titled block of aligned label/value lines."""
    print(f"{title}:\n")
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label.ljust(width)}  {value}")


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
        print(json.dumps([property_json(p) for p in props], indent=2))
    else:
        print_table(PROPERTY_HEADERS, [property_row(p) for p in props])


def shorten(value: Any, limit: int = 40) -> str:
    """Short one-line rendering of a value for the diff view."""
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
