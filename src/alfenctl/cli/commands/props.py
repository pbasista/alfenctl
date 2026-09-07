"""The property commands: ``props``, ``get``, ``set``, ``export`` and ``import``.

These are the general-purpose way at everything a charger holds.  The
named commands elsewhere in this package are shortcuts for property
writes people make often enough to deserve a name of their own.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from alfenctl import meter_map, properties, settings
from alfenctl.charger import AlfenCharger, ChargerInfo
from alfenctl.eds import VISIBLE_STRING, load_catalog
from alfenctl.repo import (
    RemotePreset,
    fetch_preset,
    fetch_preset_bytes,
    list_presets,
    pick_backoffice_variant,
)
from alfenctl.values import (
    Property,
    coerce_input,
    format_value,
    is_portable,
    merge,
    range_warning,
    values_equal,
)

from alfenctl.cli.command import Command
from alfenctl.cli.commands.meter import write_meter_map
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import (
    confirm,
    note_reboot_required,
    print_properties,
    shorten,
)
from alfenctl.cli.target import repo_config


def cmd_props(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """List charger properties (optionally filtered)."""
    catalog = load_catalog()
    props = properties.collect(charger, catalog, args.pattern, args.cat)
    if args.pattern and not props:
        print(f"No properties match '{args.pattern}'.", file=sys.stderr)
        return EXIT_ERROR
    print_properties(props, as_json=args.json)
    return EXIT_OK


def cmd_get(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Read specific properties by id or name."""
    catalog = load_catalog()
    props, errors = properties.resolve(charger, catalog, args.queries)
    for err in errors:
        print(f"error: {err}", file=sys.stderr)
    if props:
        print_properties(props, as_json=args.json)
    return EXIT_ERROR if errors else EXIT_OK


def cmd_set(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Validate and write one property."""
    catalog = load_catalog()
    props, errors = properties.resolve(charger, catalog, [args.query])
    for err in errors:
        print(f"error: {err}", file=sys.stderr)
    if not props:
        return EXIT_ERROR
    if len(props) > 1:
        print(
            f"error: '{args.query}' is ambiguous; use an id: "
            + ", ".join(p.id_str for p in props),
            file=sys.stderr,
        )
        return EXIT_ERROR
    prop = props[0]
    if not prop.writable:
        print(f"error: {prop.id_str} ({prop.name}) is read-only", file=sys.stderr)
        return EXIT_ERROR
    try:
        value = coerce_input(prop, args.value)
    except ValueError as exc:
        print(f"error: invalid value: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if prop.live is None:
        print(f"error: {prop.id_str} not found on the charger", file=sys.stderr)
        return EXIT_ERROR
    objection = range_warning(prop.key, value)
    if objection is not None:
        print(f"warning: {objection}", file=sys.stderr)
    charger.write_properties({prop.key: (value, prop.data_type)})
    (after,) = charger.fetch_properties_by_ids([prop.key])
    print(
        f"{after.id} {prop.name} = {format_value(merge(after, prop.definition), None)}"
    )
    note_reboot_required([prop.key])
    return EXIT_OK


def cmd_export(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Dump properties (id, name, value) to a JSON file or stdout."""
    catalog = load_catalog()
    props = properties.collect(charger, catalog, args.pattern, args.cat)
    kept = [p for p in props if not args.writable_only or p.writable]
    as_exml = args.exml or str(args.file or "").lower().endswith(
        settings.ENCRYPTED_SUFFIX
    )
    as_xml = (
        as_exml
        or args.xml
        or str(args.file or "").lower().endswith(settings.PLAIN_SUFFIX)
    )
    # Both the XML header and the default filename want the charger's
    # identity, and reading it is a whole category walk; neither, one or
    # both may be needed, so read it at most once, and only if asked.
    cached: ChargerInfo | None = None

    def info() -> ChargerInfo:
        nonlocal cached
        if cached is None:
            cached = charger.basic_info()
        return cached

    if as_xml:
        # The app's own settings format, which it and its presets both use.
        payload = settings.build(
            [(p.id_str, p.encoded(p.value)) for p in kept],
            model=info().model or "",
            sockets=str(info().sockets or ""),
            identity=info().identity or info().object_id,
            host=charger.station.ip,
            port=str(charger.station.port),
        )
        if as_exml:
            payload = settings.encrypt_exml(payload)
    else:
        payload = (
            json.dumps(
                [{"id": p.id_str, "name": p.name, "value": p.value} for p in kept],
                indent=2,
            )
            + "\n"
        )
    doc = kept
    file = args.file
    if file in (None, "-") and sys.stdout.isatty():
        # Default to a named file when writing to a terminal: the charger's
        # object id (serial) keeps one dump per device distinguishable.
        suffix = (
            settings.ENCRYPTED_SUFFIX
            if as_exml
            else settings.PLAIN_SUFFIX
            if as_xml
            else ".json"
        )
        file = f"{info().object_id or 'charger'}{suffix}"
    if file in (None, "-"):
        sys.stdout.write(payload)
        return EXIT_OK
    path = Path(file)
    if path.exists() and not args.yes:
        if not confirm(f"'{file}' already exists. Overwrite?"):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    path.write_text(payload, encoding="utf-8")
    print(f"Wrote {len(doc)} properties to {file}", file=sys.stderr)
    return EXIT_OK


def _load_import_file(path: str) -> list[dict[str, Any]]:
    """Read a property file: alfenctl's JSON, or the app's XML settings format.

    The format is recognised from the content, not the name, so a settings
    file saved under any extension still loads.
    """
    text = Path(path).read_text(encoding="utf-8")
    if text.lstrip().startswith("<") or settings.looks_encrypted(text):
        return list(settings.parse(text).as_entries())
    return _load_json_import_file(text)


def _load_json_import_file(text: str) -> list[dict[str, Any]]:
    """Read an export file: a list of {id, value} entries (name optional)."""
    data = json.loads(text)
    if not isinstance(data, list) or not all(
        isinstance(e, dict) and "id" in e and "value" in e for e in data
    ):
        raise ValueError('expected a JSON array of {"id", "value"} entries')
    return data


def cmd_import(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Apply a property file to the charger, with a diff preview first."""
    try:
        entries = _load_import_file(args.file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {args.file}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return _apply_entries(charger, entries, args)


def _apply_entries(
    charger: AlfenCharger,
    entries: list[dict[str, Any]],
    args: argparse.Namespace,
) -> int:
    """Diff ``entries`` against the charger, preview, confirm, and write."""
    catalog = load_catalog()
    queries = [str(e["id"]) for e in entries]
    props, errors = properties.resolve(charger, catalog, queries)
    by_query = {p.id_str: p for p in props}
    skipped_ro: list[str] = []
    skipped_bound: list[Property] = []
    writes: dict[tuple[int, int], tuple[Any, int | None]] = {}
    plan: list[tuple[Property, Any, Any]] = []
    for err in errors:
        print(f"warning: {err} (skipped)", file=sys.stderr)
    for entry in entries:
        prop = by_query.get(str(entry["id"]))
        if prop is None:
            continue
        if not prop.writable:
            skipped_ro.append(prop.id_str)
            continue
        if not is_portable(prop.key) and not args.force:
            # Writable, but bound to the charger it came from: serial,
            # identity, MAC, IP, SCN membership, license key, meter wiring.
            try:
                value = coerce_input(prop, entry["value"])
            except ValueError:
                continue
            if not values_equal(prop, value):
                skipped_bound.append(prop)
            continue
        try:
            value = coerce_input(prop, entry["value"])
        except ValueError as exc:
            print(f"warning: invalid value skipped: {exc}", file=sys.stderr)
            continue
        if values_equal(prop, value):
            continue  # already in the desired state
        writes[prop.key] = (value, prop.data_type)
        plan.append((prop, prop.value, value))
    if skipped_ro:
        print(
            f"note: {len(skipped_ro)} read-only properties skipped "
            f"(e.g. {', '.join(skipped_ro[:3])})",
            file=sys.stderr,
        )
    if skipped_bound:
        print(
            f"\nSkipped {len(skipped_bound)} propert"
            f"{'y' if len(skipped_bound) == 1 else 'ies'} that belong to the "
            "charger they came from:",
            file=sys.stderr,
        )
        for prop in skipped_bound:
            print(f"  {prop.id_str} {prop.name}", file=sys.stderr)
        print(
            "These identify the device (serial, identity, MAC, IP, SCN "
            "membership,\nlicense key, meter wiring); writing another "
            "charger's values here would\nmisidentify or strand it. The "
            "Windows app leaves them out of its settings\nfiles entirely. "
            "Use --force to write them anyway.",
            file=sys.stderr,
        )
    if not plan:
        print("Nothing to change; the charger already matches the file.")
        return EXIT_OK
    print(f"{len(plan)} propert{'y' if len(plan) == 1 else 'ies'} to change:\n")
    for prop, old, new in plan:
        print(
            f"  {prop.id_str} {prop.name}: {shorten(old)} -> {shorten(prop.encoded(new))}"
        )
    if args.dry_run:
        print("\nDry run; nothing written.")
        return EXIT_OK
    if not args.yes:
        if not confirm(f"\nApply {len(plan)} change(s) to the charger?"):
            print("Aborted.")
            return EXIT_ERROR
    charger.write_properties(writes)
    print(f"Applied {len(writes)} propert{'y' if len(writes) == 1 else 'ies'}.")
    note_reboot_required(writes)
    return EXIT_OK


# The backoffice properties the app empties before it installs a preset, so
# that a leftover URL or APN from the previous operator cannot survive into
# the new one (``PanelConnectivity.ClearAllBackOfficeSettings``).  The four
# network profiles it also clears are left alone here: they are a whole panel
# of their own, and clearing them is not what "apply this preset" was asked.
BACKOFFICE_CLEARED = (
    (0x2071, 1),  # backoffice URL, wired
    (0x2071, 2),  # backoffice path, wired
    (0x2078, 1),  # backoffice URL, mobile
    (0x2078, 2),  # backoffice path, mobile
    (0x2100, 0),  # gprsAPNname
    (0x2101, 0),  # gprsAPNuser
    (0x2102, 0),  # gprsAPNpassword
)
P_BACKOFFICE_NAME = (0x2076, 0)  # 8310 commBackOfficeShortName: "preset,meter"
BACKOFFICE_NAME_MAX = 50  # CombineBopresetMeterName gives up past this


def _apply_backoffice(
    charger: AlfenCharger,
    preset: RemotePreset,
    blob: bytes,
    args: argparse.Namespace,
) -> int:
    """Install a backoffice preset the way the app does: as a firmware push.

    These files are not settings documents -- they are signed blobs the
    charger unpacks itself, so nothing here can show what is inside one
    beforehand.  What the app does around the upload is what matters: empty
    the old operator's settings first, name the preset afterwards, reboot.
    """
    print(f"Preset {preset.label} ({preset.kind}), {len(blob)} bytes.")
    if args.dry_run:
        print("Dry run; nothing uploaded.")
        return EXIT_OK
    if not args.yes:
        print(
            "This clears the current backoffice settings, uploads the preset "
            "through the firmware channel, and needs a reboot to take effect.",
            file=sys.stderr,
        )
        if not confirm(f"Install {preset.label}?"):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    live = {p.key: p for p in charger.fetch_properties_by_ids(list(BACKOFFICE_CLEARED))}
    cleared = {key: ("", prop.data_type) for key, prop in live.items() if prop.writable}
    if cleared:
        charger.write_properties(cleared)
        print(
            f"Cleared {len(cleared)} backoffice propert"
            f"{'y' if len(cleared) == 1 else 'ies'}."
        )
    charger.upload_firmware(blob)
    print("Preset uploaded.")
    name = preset.label[:BACKOFFICE_NAME_MAX]
    charger.write_properties({P_BACKOFFICE_NAME: (name, VISIBLE_STRING)})
    print(f"Named it {name!r} in 2076_0.")
    print("Reboot to apply it: alfenctl reboot")
    return EXIT_OK


def cmd_preset(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """List Alfen's published presets, or apply one."""
    config = repo_config(args)
    presets = list_presets(config)
    if not presets:
        print(f"{config.site} publishes no presets.", file=sys.stderr)
        return EXIT_OK
    if args.name is None:
        return _list_presets(presets, config.site)
    wanted = args.name.lower()
    matches = [p for p in presets if wanted in (p.label.lower(), p.name.lower())] or [
        p for p in presets if wanted in p.label.lower()
    ]
    if not matches:
        print(f"error: no preset matches {args.name!r}", file=sys.stderr)
        return EXIT_ERROR
    labels = {p.label for p in matches}
    if len(labels) > 1:
        print(f"{args.name!r} matches several presets:", file=sys.stderr)
        for label in sorted(labels):
            print(f"  {label}", file=sys.stderr)
        return EXIT_ERROR
    if len(matches) > 1:
        # One preset published once per encryption key; the firmware decides.
        info = charger.basic_info()
        chosen = pick_backoffice_variant(matches, info.firmware_version)
        assert chosen is not None
        preset = chosen
    else:
        preset = matches[0]
    if preset.is_backoffice:
        blob = fetch_preset_bytes(preset, config)
        if args.save:
            Path(args.save).write_bytes(blob)
            print(f"Wrote {preset.name} to {args.save}")
            return EXIT_OK
        return _apply_backoffice(charger, preset, blob, args)
    text = fetch_preset(preset, config)
    if args.save:
        Path(args.save).write_text(text, encoding="utf-8")
        print(f"Wrote {preset.name} to {args.save}")
        return EXIT_OK
    if preset.is_meter_map:
        # A register map is not a property dump: it goes through the same
        # bracketed write as `meter-map apply`.
        wanted = meter_map.parse_json(text)
        current = meter_map.read(charger)
        return write_meter_map(charger, wanted, current, args)
    print(f"Applying preset {preset.label} ({preset.kind}).\n")
    return _apply_entries(charger, settings.parse(text).as_entries(), args)


def _list_presets(presets: list[RemotePreset], site: str) -> int:
    """Print what is published, without printing nine hundred backoffices."""
    meters = [p for p in presets if not p.is_backoffice]
    backoffice = sorted({p.label for p in presets if p.is_backoffice})
    print(f"Presets on {site}:\n")
    if meters:
        width = max(len(p.label) for p in meters)
        for preset in meters:
            stamp = preset.modified.strftime("%Y-%m-%d") if preset.modified else ""
            print(f"  {preset.label.ljust(width)}  {preset.kind:22s}  {stamp}")
    if backoffice:
        # There are hundreds of these, one per operator; listing them all
        # buries the handful of meter maps nobody can find another way.
        print(f"\n  ...and {len(backoffice)} backoffice presets.")
        print("  Search them with: alfenctl preset <part of the name>")
    print("\nApply one with: alfenctl preset <name>")
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "props",
        help="list charger properties and their values",
        aliases=["ls"],
        parents=[common],
    )
    sp.add_argument("pattern", nargs="?", help="glob filter on id/name/title")
    sp.add_argument("--cat", help="only this property category")
    sp.add_argument("--json", action="store_true", help="full metadata as JSON")

    sp = sub.add_parser("get", help="read properties by id or name", parents=[common])
    sp.add_argument("queries", nargs="+", help="property ids or names")
    sp.add_argument("--json", action="store_true", help="full metadata as JSON")

    sp = sub.add_parser("set", help="write one property", parents=[common])
    sp.add_argument("query", help="property id or name")
    sp.add_argument("value", help="value to write")

    sp = sub.add_parser(
        "export",
        help="dump properties to JSON (file or stdout)",
        aliases=["dump"],
        parents=[common],
    )
    sp.add_argument(
        "file",
        nargs="?",
        help="output file (default: <object-id>.json to a terminal, else stdout)",
    )
    sp.add_argument("pattern", nargs="?", help="glob filter on id/name/title")
    sp.add_argument("--cat", help="only this property category")
    sp.add_argument(
        "--writable-only", action="store_true", help="skip read-only properties"
    )
    sp.add_argument(
        "--xml",
        action="store_true",
        help="write the Windows app's settings format instead of JSON "
        "(implied by a .xml output file)",
    )
    sp.add_argument(
        "--exml",
        action="store_true",
        help="encrypt the settings XML the way the app does (implied by a "
        ".exml output file)",
    )
    sp.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="overwrite an existing output file without asking",
    )

    sp = sub.add_parser(
        "import",
        help="apply a JSON property dump",
        aliases=["restore"],
        parents=[common],
    )
    sp.add_argument("file", help="JSON file written by export")
    sp.add_argument(
        "--dry-run", action="store_true", help="preview the diff, write nothing"
    )
    sp.add_argument(
        "--force",
        action="store_true",
        help="also write device-bound properties (serial, identity, MAC, IP, "
        "SCN membership, license key, meter wiring), which are skipped by "
        "default because they belong to the charger the dump came from",
    )
    sp.add_argument("-y", "--yes", action="store_true", help="do not prompt")

    sp = sub.add_parser(
        "preset",
        help="list or apply the presets Alfen publishes",
        description="List the presets Alfen publishes beside its firmware, "
        "or apply one. Three kinds live there: custom Modbus register maps "
        "for an energy meter, property settings, and the several hundred "
        "backoffice presets -- which are signed blobs rather than documents, "
        "so installing one clears the current backoffice settings, uploads it "
        "through the firmware channel, names it in 0x2076_0 and needs a "
        "reboot. NAME may be part of a name, which searches.",
        parents=[common],
    )
    sp.add_argument(
        "name", nargs="?", help="preset to apply (omit to list what is published)"
    )
    sp.add_argument(
        "--save", metavar="FILE", help="write the preset to a file instead of applying"
    )
    sp.add_argument(
        "--dry-run", action="store_true", help="preview the changes, write nothing"
    )
    sp.add_argument(
        "--force",
        action="store_true",
        help="also write device-bound properties (see import --force)",
    )
    sp.add_argument("-y", "--yes", action="store_true", help="do not prompt")


COMMANDS: dict[str, Command] = {
    "props": Command(cmd_props),
    "ls": Command(cmd_props),
    "get": Command(cmd_get),
    "set": Command(cmd_set),
    "export": Command(cmd_export),
    "dump": Command(cmd_export),
    "import": Command(cmd_import),
    "restore": Command(cmd_import),
    "preset": Command(cmd_preset),
}
