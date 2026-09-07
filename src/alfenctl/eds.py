"""The static property catalog parsed from the vendor's EDS file.

The Windows installer ships a CANopen-style EDS XML (``app/EDS.xml`` inside
the installer archive) that describes every charger property the app knows:
its numeric object id, parameter name, display title, data type, access
mode, default value, unit and enumerated options.  The charger's own
``GET /api/prop`` replies carry only ``id``/``value``/``type``/``access``/
``len``/``cat`` -- the names, titles and enums exist solely in this file,
which is why we bundle it with the package and merge the two views in the
CLI (``EDSParser.Parse`` + ``ICUPropertyDictionary`` in the app).

The EDS id attribute is either ``"2050"`` (sub-index 0) or ``"2221subA"``
(an explicit sub-index), always hexadecimal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from xml.etree import ElementTree

# --- CANopen / SDT data type codes (SDT.cs; the EDS uses the same values) -----------------

BOOLEAN = 1
INTEGER8 = 2
INTEGER16 = 3
INTEGER32 = 4
UNSIGNED8 = 5
UNSIGNED16 = 6
UNSIGNED32 = 7
REAL32 = 8
VISIBLE_STRING = 9
OCTET_STRING = 10
UNICODE_STRING = 11
DOMAIN = 15
INTEGER64 = 21
REAL64 = 17
UNSIGNED64 = 27  # 0x001B
BYTEARRAY = 64
ARRAY_16 = 65

# Short human-readable names for the type codes, for table/JSON output.
TYPE_NAMES = {
    BOOLEAN: "bool",
    INTEGER8: "i8",
    INTEGER16: "i16",
    INTEGER32: "i32",
    INTEGER64: "i64",
    UNSIGNED8: "u8",
    UNSIGNED16: "u16",
    UNSIGNED32: "u32",
    UNSIGNED64: "u64",
    REAL32: "f32",
    REAL64: "f64",
    VISIBLE_STRING: "str",
    OCTET_STRING: "oct",
    UNICODE_STRING: "ustr",
    DOMAIN: "domain",
    BYTEARRAY: "bytes",
    ARRAY_16: "u16[]",
}

# --- Access modes (EDS AccessType) ---------------------------------------------------------

# Anything other than these is writable ("rw", "rww", "rwr", "wo").
READ_ONLY_ACCESS = frozenset({"r", "ro"})

# The default (English) language tag the EDS uses for Titles/Units/Options.
DEFAULT_LANG = ""

# "<hex>" or "<hex>sub<hex>", case-insensitive, as in the EDS id attribute.
EDS_ID_RE = re.compile(r"([0-9A-Fa-f]+)(?:sub([0-9A-Fa-f]+))?$")

# Where the bundled EDS file lives (a package data file).
EDS_FILENAME = "EDS.xml"


def type_name(data_type: int | None) -> str:
    """Return the short display name for a type code (``"?"`` if unknown)."""
    return TYPE_NAMES.get(data_type, "?") if data_type is not None else "?"


@dataclass(frozen=True)
class Option:
    """One enumerated choice of a property: a stored value and its label."""

    value: str
    title: str


@dataclass(frozen=True)
class PropertyDef:
    """A property as described by the EDS catalog (no live value)."""

    prop_id: int
    sub_id: int
    name: str
    title: str
    data_type: int | None
    access: str
    length: int | None = None
    default: str | None = None
    unit: str = ""
    options: tuple[Option, ...] = ()

    @property
    def writable(self) -> bool:
        """Whether the EDS marks this property as not read-only."""
        return self.access not in READ_ONLY_ACCESS

    @property
    def id_str(self) -> str:
        """The charger-style id, e.g. ``"2050_0"`` (single-width hex)."""
        return f"{self.prop_id:X}_{self.sub_id:X}"

    def matches(self, pattern: str) -> bool:
        """Case-insensitively glob-match the pattern against id/name/title."""
        p = pattern.lower()
        return (
            fnmatch(self.id_str.lower(), p)
            or fnmatch(self.name.lower(), p)
            or fnmatch(self.title.lower(), p)
        )


class PropertyCatalog:
    """All EDS property definitions, lookable up by id or by parameter name."""

    def __init__(self, defs: list[PropertyDef]) -> None:
        """Index ``defs`` by (propId, subId) and by parameter name."""
        self._by_key: dict[tuple[int, int], PropertyDef] = {}
        self._by_name: dict[str, list[PropertyDef]] = {}
        for d in defs:
            if (d.prop_id, d.sub_id) in self._by_key:  # duplicate EDS <Object>
                continue
            self._by_key[(d.prop_id, d.sub_id)] = d
            self._by_name.setdefault(d.name.lower(), []).append(d)

    def __len__(self) -> int:
        """Return the number of known property definitions."""
        return len(self._by_key)

    def get(self, key: tuple[int, int]) -> PropertyDef | None:
        """Return the definition for ``(propId, subId)``, or None."""
        return self._by_key.get(key)

    def get_by_name(self, name: str) -> list[PropertyDef]:
        """Return all definitions whose parameter name equals ``name``."""
        return list(self._by_name.get(name.lower(), ()))

    def all(self) -> list[PropertyDef]:
        """Return all definitions sorted by (propId, subId)."""
        return [self._by_key[k] for k in sorted(self._by_key)]


def _lang_text(parent: ElementTree.Element, tag: str) -> str:
    """Return the English/default-language text of the first ``<tag>`` child."""
    for el in parent.findall(tag):
        if el.get("Lang", DEFAULT_LANG) == DEFAULT_LANG and el.text:
            return el.text.strip()
    return ""


def _parse_id(raw: str) -> tuple[int, int] | None:
    """Parse an EDS id attribute (``"2050"`` / ``"2221subA"``) to ``(id, sub)``."""
    m = EDS_ID_RE.fullmatch(raw.strip())
    if m is None:
        return None
    return int(m.group(1), 16), int(m.group(2) or "0", 16)


def _parse_type(raw: str | None) -> int | None:
    """Parse a ``"0x0009"``-style DataType attribute to its numeric code."""
    if not raw:
        return None
    try:
        return int(raw, 16)
    except ValueError:
        return None


def load_catalog(path: Path | None = None) -> PropertyCatalog:
    """Parse the EDS file (default: the copy bundled with the package)."""
    if path is None:
        path = Path(__file__).with_name(EDS_FILENAME)
    root = ElementTree.parse(path).getroot()
    defs: list[PropertyDef] = []
    for obj in root.findall("Object"):
        parsed = _parse_id(obj.get("Id", ""))
        if parsed is None:
            continue
        prop_id, sub_id = parsed
        options = tuple(
            Option(value=o.get("Value", ""), title=_lang_text(o, "Title"))
            for o in obj.findall("Option")
        )
        title = _lang_text(obj, "Title") or _first_node_title(obj)
        length_raw = obj.get("Length")
        defs.append(
            PropertyDef(
                prop_id=prop_id,
                sub_id=sub_id,
                name=obj.get("ParameterName", "") or f"{prop_id:X}_{sub_id:X}",
                title=title,
                data_type=_parse_type(obj.get("DataType")),
                access=obj.get("AccessType", "rw"),
                length=int(length_raw) if length_raw and length_raw.isdigit() else None,
                default=obj.get("DefaultValue"),
                unit=_lang_text(obj, "Units"),
                options=options,
            )
        )
    return PropertyCatalog(defs)


def _first_node_title(obj: ElementTree.Element) -> str:
    """Fallback title: the first per-socket ``<Node>``'s English title."""
    for node in obj.findall("Node"):
        text = _lang_text(node, "Title")
        if text:
            return text
    return ""


# --- User-facing id parsing ----------------------------------------------------------------

# A query is an id ("2050", "2050_1", "2050sub1", hex, case-insensitive); the
# separator is an underscore, a space, or the EDS-style "sub" infix.  Alfen
# ids are always shown hex, so "2050" means 0x2050, never decimal.
ID_QUERY_RE = re.compile(r"([0-9A-Fa-f]+)(?:(?:[_ ]|sub)([0-9A-Fa-f]+))?$")


def parse_id_query(query: str) -> tuple[int, int] | None:
    """Parse a user-supplied property id query into ``(propId, subId)``.

    Accepts ``"2050"``, ``"2050_1"``, ``"2050sub1"`` (hex, case-insensitive).
    Returns None when the query is not id-shaped (then it is a parameter
    name, resolved against the catalog by the caller).
    """
    m = ID_QUERY_RE.fullmatch(query.strip())
    if m is None:
        return None
    return int(m.group(1), 16), int(m.group(2) or "0", 16)
