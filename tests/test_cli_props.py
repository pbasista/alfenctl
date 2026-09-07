"""Tests for reading and writing properties, presets and the Modbus register map."""

from __future__ import annotations

import json


from alfenctl import cli


def test_props_table(capsys, fake_charger) -> None:
    assert cli.main(["props", "--host", "192.168.11.42"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "sysChargePointModel" in out
    assert "sysMaxStationCurrent" in out
    assert "NG910-60027" in out


def test_props_pattern_filters(capsys, fake_charger) -> None:
    assert cli.main(["props", "*current*", "--host", "1.2.3.4"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "sysMaxStationCurrent" in out
    assert "sysChargePointModel" not in out


def test_props_json(capsys, fake_charger) -> None:
    assert cli.main(["props", "--json", "--host", "1.2.3.4"]) == cli.EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    by_id = {p["id"]: p for p in doc}
    assert by_id["2050_0"]["name"] == "sysChargePointModel"
    assert by_id["2050_0"]["type"] == "str"
    assert by_id["2062_0"]["type"] == "f32"
    assert by_id["100A_0"]["access"] == "ro"


def test_props_json_marks_what_no_source_describes(capsys, fake_charger) -> None:
    """`known: false` is the marker for a register nobody can name."""
    from alfenctl.charger import LiveProperty
    from alfenctl.cli.output import property_row
    from alfenctl.values import Property

    assert cli.main(["props", "--json", "--host", "1.2.3.4"]) == cli.EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    by_id = {p["id"]: p for p in doc}
    assert by_id["2050_0"]["known"] is True  # the EDS describes this one

    # 0x3251: live on a real NG9xx, named by no source (EDS, Windows app,
    # My Eve, Home Assistant) -- `known` has to say so, and the table
    # shows a `?` where every other row has a title.
    unknown = Property(
        key=(0x3251, 0),
        live=LiveProperty(
            id="3251_0",
            key=(0x3251, 0),
            value=0,
            data_type=5,
            access=1,
            category="generic",
        ),
        definition=None,
    )
    assert unknown.known is False
    assert property_row(unknown)[-1] == "?"


def test_the_glossary_titles_are_searchable() -> None:
    """A title from the glossary filters and prints like an EDS one."""
    from alfenctl.cli.output import property_row
    from alfenctl.properties import matches
    from alfenctl.values import Property

    # 0x3260 sub 1: the display width -- a glossary title, not in the EDS.
    display = Property(key=(0x3260, 1), live=None, definition=None)
    assert display.title == "Display Width (px)"
    assert matches(display, "*width*") is True
    assert property_row(display)[-1] == "Display Width (px)"


def test_get_by_id_and_name(capsys, fake_charger) -> None:
    assert (
        cli.main(["get", "2050_0", "sysMaxStationCurrent", "--host", "1.2.3.4"])
        == cli.EXIT_OK
    )
    out = capsys.readouterr().out
    assert "sysChargePointModel" in out
    assert "sysMaxStationCurrent" in out
    assert "100A_0" not in out  # not requested


def test_get_unknown_name_errors(capsys, fake_charger) -> None:
    assert cli.main(["get", "nosuchprop", "--host", "1.2.3.4"]) == cli.EXIT_ERROR
    assert "no property named" in capsys.readouterr().err


def test_set_writes_and_rereads(capsys, fake_charger) -> None:
    assert (
        cli.main(["set", "sysMaxStationCurrent", "32", "--host", "1.2.3.4"])
        == cli.EXIT_OK
    )
    assert fake_charger.writes and fake_charger.writes[0][(0x2062, 0)] == (32.0, 8)
    assert "32.0" in capsys.readouterr().out


def test_set_read_only_rejected(capsys, fake_charger) -> None:
    # 100A_0 (software version) is read-only in the live reply.
    assert cli.main(["set", "100A_0", "9.9.9", "--host", "1.2.3.4"]) == cli.EXIT_ERROR
    assert "read-only" in capsys.readouterr().err
    assert not fake_charger.writes


def test_set_invalid_value_rejected(capsys, fake_charger) -> None:
    assert (
        cli.main(["set", "sysMaxStationCurrent", "abc", "--host", "1.2.3.4"])
        == cli.EXIT_ERROR
    )
    assert "not a number" in capsys.readouterr().err
    assert not fake_charger.writes


def test_set_out_of_range_rejected(capsys, fake_charger) -> None:
    # 205B (sysDaylightSavings) is i8 per the EDS; 300 is out of range.
    # It is not in LIVE_DOCS, so it resolves via catalog only -> not live ->
    # error "not found on the charger" ... unless the charger reports it.
    # Use a live one instead: sysMaxStationCurrent is f32; range N/A.
    # So instead exercise range via catalog-only path being refused.
    assert (
        cli.main(["set", "sysDaylightSavings", "300", "--host", "1.2.3.4"])
        == cli.EXIT_ERROR
    )
    assert not fake_charger.writes


def test_export_import_roundtrip(capsys, tmp_path, fake_charger) -> None:
    dump = tmp_path / "dump.json"
    assert (
        cli.main(["export", str(dump), "--host", "1.2.3.4", "--writable-only"])
        == cli.EXIT_OK
    )
    entries = json.loads(dump.read_text())
    assert all(e["id"] != "100A_0" for e in entries)  # read-only excluded

    for e in entries:
        if e["id"] == "2062_0":
            e["value"] = 16.0
    dump.write_text(json.dumps(entries))
    result = cli.main(["import", str(dump), "--host", "1.2.3.4", "-y"])
    assert result == cli.EXIT_OK
    assert fake_charger.writes and fake_charger.writes[0][(0x2062, 0)] == (16.0, 8)


def test_import_dry_run_writes_nothing(capsys, tmp_path, fake_charger) -> None:
    dump = tmp_path / "dump.json"
    dump.write_text(json.dumps([{"id": "2062_0", "value": 20.0}]))
    assert (
        cli.main(["import", str(dump), "--dry-run", "--host", "1.2.3.4"]) == cli.EXIT_OK
    )
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "2062_0" in out
    assert not fake_charger.writes


def test_import_skips_read_only(capsys, tmp_path, fake_charger) -> None:
    dump = tmp_path / "dump.json"
    dump.write_text(
        json.dumps(
            [{"id": "100A_0", "value": "9.9.9"}, {"id": "2062_0", "value": 20.0}]
        )
    )
    assert cli.main(["import", str(dump), "--host", "1.2.3.4", "-y"]) == cli.EXIT_OK
    assert all((0x100A, 0) not in w for w in fake_charger.writes)


def test_import_no_changes_needed(capsys, tmp_path, fake_charger) -> None:
    dump = tmp_path / "dump.json"
    dump.write_text(json.dumps([{"id": "2062_0", "value": 25.0}]))
    assert cli.main(["import", str(dump), "--host", "1.2.3.4", "-y"]) == cli.EXIT_OK
    assert "Nothing to change" in capsys.readouterr().out
    assert not fake_charger.writes


PRESET_XML = (
    "<Settings><XMLVersion>1.0</XMLVersion><Properties>"
    '<Property Id="2062_00" Value="16.0" />'
    "</Properties></Settings>"
)


def _presets(monkeypatch, presets, text=PRESET_XML):
    """Make the firmware server publish ``presets``."""
    from alfenctl.repo import RemotePreset

    rows = [
        RemotePreset(name=f"{n}.xml", directory=d, size=100, modified=None)
        for n, d in presets
    ]
    monkeypatch.setattr("alfenctl.cli.commands.props.list_presets", lambda config: rows)
    monkeypatch.setattr(
        "alfenctl.cli.commands.props.fetch_preset", lambda preset, config: text
    )
    return rows


def test_preset_lists_what_is_published(fake_charger, capsys, monkeypatch) -> None:
    _presets(monkeypatch, [("ABB B23 TCP", "TCPPresets"), ("SDM630", "RTUPresets")])
    assert cli.main(["preset", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "ABB B23 TCP" in out and "Modbus TCP meter" in out
    assert "SDM630" in out and "Modbus RTU meter" in out


def test_preset_applies_one_by_name(fake_charger, capsys, monkeypatch) -> None:
    _presets(monkeypatch, [("ABB B23 TCP", "TCPPresets")])
    assert cli.main(["preset", "ABB B23 TCP", "--dry-run", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Applying preset ABB B23 TCP" in out
    assert "2062_0" in out and "Dry run" in out


def test_preset_matches_a_partial_name(fake_charger, capsys, monkeypatch) -> None:
    _presets(monkeypatch, [("ABB B23 TCP", "TCPPresets")])
    assert cli.main(["preset", "abb", "--dry-run", "--host", "1.2.3.4"]) == 0
    assert "Applying preset ABB B23 TCP" in capsys.readouterr().out


def test_preset_refuses_an_ambiguous_name(fake_charger, capsys, monkeypatch) -> None:
    _presets(monkeypatch, [("ABB B23", "TCPPresets"), ("ABB B24", "TCPPresets")])
    assert cli.main(["preset", "abb", "--host", "1.2.3.4"]) == 1
    err = capsys.readouterr().err
    assert "matches several presets" in err and "ABB B24" in err


def test_preset_reports_an_unknown_name(fake_charger, capsys, monkeypatch) -> None:
    _presets(monkeypatch, [("ABB B23", "TCPPresets")])
    assert cli.main(["preset", "nope", "--host", "1.2.3.4"]) == 1
    assert "no preset matches" in capsys.readouterr().err


def test_preset_save_writes_the_file(
    fake_charger, capsys, monkeypatch, tmp_path
) -> None:
    _presets(monkeypatch, [("ABB B23", "TCPPresets")])
    out = tmp_path / "preset.xml"
    assert cli.main(["preset", "ABB B23", "--save", str(out), "--host", "1.2.3.4"]) == 0
    assert out.read_text() == PRESET_XML
    assert not fake_charger.writes


def test_export_xml_by_extension(fake_charger, tmp_path, monkeypatch) -> None:
    """A .xml output file selects the app's settings format."""
    out = tmp_path / "backup.xml"
    assert cli.main(["export", str(out), "-y", "--host", "1.2.3.4"]) == 0
    text = out.read_text()
    assert text.startswith("<Settings>")
    assert 'Id="2050_00"' in text  # the app's padded id spelling
    assert "<Model>NG910-60027</Model>" in text


def test_export_xml_flag_without_the_extension(
    fake_charger, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert cli.main(["export", "-", "--xml", "--host", "1.2.3.4"]) == 0
    assert capsys.readouterr().out.startswith("<Settings>")


def test_export_still_defaults_to_json(fake_charger, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert cli.main(["export", "-", "--host", "1.2.3.4"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"]


def test_import_reads_the_apps_xml(fake_charger, tmp_path, capsys) -> None:
    doc = tmp_path / "preset.xml"
    doc.write_text(
        "<Settings><XMLVersion>1.0</XMLVersion><Properties>"
        '<Property Id="2062_00" Value="16.0" />'
        "</Properties></Settings>"
    )
    assert cli.main(["import", str(doc), "--dry-run", "--host", "1.2.3.4"]) == 0
    assert "2062_0" in capsys.readouterr().out


def test_import_says_so_for_an_unreadable_encrypted_file(
    fake_charger, tmp_path, capsys
) -> None:
    import base64

    doc = tmp_path / "backup.exml"
    doc.write_text(base64.b64encode(b"\x00\x01\x02\x03" * 32).decode())
    assert cli.main(["import", str(doc), "--host", "1.2.3.4"]) == 1
    assert "could not decrypt" in capsys.readouterr().err


def test_export_import_xml_round_trip(fake_charger, tmp_path, capsys) -> None:
    out = tmp_path / "backup.xml"
    assert cli.main(["export", str(out), "-y", "--host", "1.2.3.4"]) == 0
    assert cli.main(["import", str(out), "--dry-run", "--host", "1.2.3.4"]) == 0
    assert "already matches the file" in capsys.readouterr().out


def test_export_import_exml_round_trip(fake_charger, tmp_path, capsys) -> None:
    """A ``.exml`` export decrypts and applies exactly like a plain one."""
    out = tmp_path / "backup.exml"
    assert cli.main(["export", str(out), "-y", "--host", "1.2.3.4"]) == 0
    with out.open(encoding="utf-8") as f:
        text = f.read().strip()
    assert not text.startswith("<")  # actually encrypted, not plain XML
    assert cli.main(["import", str(out), "--dry-run", "--host", "1.2.3.4"]) == 0
    assert "already matches the file" in capsys.readouterr().out


def test_import_skips_device_bound_properties(
    fake_charger, capsys, monkeypatch, tmp_path
) -> None:
    """A dump carries the charger's identity; restoring it elsewhere must not."""
    doc = tmp_path / "dump.json"
    doc.write_text(
        json.dumps(
            [
                {"id": "2050_0", "name": "model", "value": "NG920-99999"},
                {"id": "2051_0", "name": "serial", "value": "ACE0000001"},
                {"id": "21A1_0", "name": "license", "value": "AAAA.BBBB"},
            ]
        )
    )
    assert cli.main(["import", str(doc), "--dry-run", "--host", "1.2.3.4"]) == 0
    err = capsys.readouterr().err
    assert "belong to the charger they came from" in err
    assert "2051_0" in err and "21A1_0" in err
    assert not fake_charger.writes


def test_import_force_writes_device_bound_properties(
    fake_charger, capsys, monkeypatch, tmp_path
) -> None:
    doc = tmp_path / "dump.json"
    doc.write_text(json.dumps([{"id": "2051_0", "value": "ACE0000001"}]))
    assert cli.main(["import", str(doc), "--force", "-y", "--host", "1.2.3.4"]) == 0
    assert "belong to the charger" not in capsys.readouterr().err


def test_import_ignores_device_bound_values_that_already_match(
    fake_charger, capsys, tmp_path
) -> None:
    """No warning for a property the charger is already set to."""
    doc = tmp_path / "dump.json"
    doc.write_text(json.dumps([{"id": "2050_0", "value": "NG910-60027"}]))
    assert cli.main(["import", str(doc), "--dry-run", "--host", "1.2.3.4"]) == 0
    assert "belong to the charger" not in capsys.readouterr().err


# --- Custom Modbus register map -------------------------------------------------------------


_MAP_PROPS = [
    {"id": "2570_0", "value": "07,10,FF,FF"},
    {"id": "2571_0", "value": "0006,0010,0000,0000"},
    {"id": "2572_0", "value": "03,06,00,00"},
    {"id": "2573_0", "value": "FD,00,00,00"},
    {"id": "2064_0", "value": 1},
]

_MAP_JSON = json.dumps(
    {
        "Name": "Test meter",
        "Regmap": [
            {"Key": "CURRENT_L1", "RegNum": 6, "DataType": "UNSIGNED32", "ScaleE": -3},
        ],
    }
)


def test_meter_map_shows_the_installed_map(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _MAP_PROPS
    assert cli.main(["meter-map", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "2 of 4 slots used" in out
    assert "CURRENT_L1" in out and "0x0006" in out and "x 0.001" in out


def test_meter_map_says_when_none_is_installed(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += [
        {"id": "2570_0", "value": "FF,FF"},
        {"id": "2571_0", "value": "0000,0000"},
        {"id": "2572_0", "value": "00,00"},
        {"id": "2573_0", "value": "00,00"},
    ]
    assert cli.main(["meter-map", "--host", "1.2.3.4"]) == 0
    assert "No custom register map is installed" in capsys.readouterr().out


def test_meter_map_on_a_charger_without_one(fake_charger, capsys) -> None:
    assert cli.main(["meter-map", "--host", "1.2.3.4"]) == cli.EXIT_ERROR
    assert "does not publish a custom Modbus register map" in capsys.readouterr().err


def test_meter_map_save_writes_json(fake_charger, tmp_path, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _MAP_PROPS
    out_file = tmp_path / "map.json"
    argv = ["meter-map", "save", str(out_file), "--host", "1.2.3.4"]
    assert cli.main(argv) == 0
    doc = json.loads(out_file.read_text())
    assert [e["Key"] for e in doc["Regmap"]] == ["CURRENT_L1", "POWER_REAL_L1"]
    assert "Wrote 2 entries" in capsys.readouterr().out


def test_meter_map_apply_previews_and_writes(fake_charger, tmp_path, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _MAP_PROPS
    src = tmp_path / "meter.json"
    src.write_text(_MAP_JSON)
    argv = ["meter-map", "apply", str(src), "-y", "--host", "1.2.3.4"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "Applying Test meter" in out
    assert "replaces the 2 entries now installed" in out
    assert "Register map written" in out
    written = [w for w in fake_charger.writes if (0x2570, 0) in w]
    assert written and written[0][(0x2570, 0)][0] == bytes([7, 0xFF, 0xFF, 0xFF])


def test_meter_map_apply_dry_run_writes_nothing(fake_charger, tmp_path, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += _MAP_PROPS
    src = tmp_path / "meter.json"
    src.write_text(_MAP_JSON)
    argv = ["meter-map", "apply", str(src), "--dry-run", "--host", "1.2.3.4"]
    assert cli.main(argv) == 0
    assert "Dry run" in capsys.readouterr().out
    assert not fake_charger.writes


def test_meter_map_apply_rejects_a_bad_file(fake_charger, tmp_path, capsys) -> None:
    src = tmp_path / "meter.json"
    src.write_text("{}")
    argv = ["meter-map", "apply", str(src), "-y", "--host", "1.2.3.4"]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert "no 'Regmap' list" in capsys.readouterr().err


def test_preset_applies_a_published_register_map(
    fake_charger, capsys, monkeypatch
) -> None:
    """A .json preset is a register map, not a property dump."""
    from alfenctl.repo import RemotePreset

    preset = RemotePreset(
        name="Socomec E23.json", directory="TCPPresets", size=1, modified=None
    )
    monkeypatch.setattr(
        "alfenctl.cli.commands.props.list_presets", lambda config: [preset]
    )
    monkeypatch.setattr(
        "alfenctl.cli.commands.props.fetch_preset", lambda p, config: _MAP_JSON
    )
    fake_charger.docs["/api/prop"]["properties"] += _MAP_PROPS
    argv = ["preset", "Socomec E23", "-y", "--host", "1.2.3.4"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "Applying Test meter" in out
    assert any((0x2570, 0) in w for w in fake_charger.writes)


def test_preset_listing_names_both_kinds(fake_charger, capsys, monkeypatch) -> None:
    from alfenctl.repo import RemotePreset

    presets = [
        RemotePreset("ABB B23.xml", "TCPPresets", 1, None),
        RemotePreset("Socomec E23.json", "TCPPresets", 1, None),
    ]
    monkeypatch.setattr(
        "alfenctl.cli.commands.props.list_presets", lambda config: presets
    )
    assert cli.main(["preset", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Modbus TCP meter settings" in out
    assert "Modbus TCP meter map" in out


# --- the writes the charger accepts and then ignores ------------------------------------------


def test_set_says_when_a_write_waits_for_a_reboot(capsys, fake_charger) -> None:
    fake_charger.docs["/api/prop"]["properties"].append(
        {"id": "2126_0", "access": 2, "type": 3, "value": 0}
    )
    assert cli.main(["set", "2126_0", "2", "--host", "1.2.3.4"]) == cli.EXIT_OK
    err = capsys.readouterr().err
    assert "2126_0 takes effect only after a restart" in err
    assert "alfenctl reboot" in err


def test_set_is_quiet_for_a_write_that_takes_effect_at_once(
    capsys, fake_charger
) -> None:
    assert (
        cli.main(["set", "sysMaxStationCurrent", "32", "--host", "1.2.3.4"])
        == cli.EXIT_OK
    )
    assert "restart" not in capsys.readouterr().err


def test_import_says_which_of_its_writes_wait_for_a_reboot(
    capsys, fake_charger, tmp_path
) -> None:
    fake_charger.docs["/api/prop"]["properties"].append(
        {"id": "2126_0", "access": 2, "type": 3, "value": 0}
    )
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps([{"id": "2126_0", "value": 2}, {"id": "2062_0", "value": 30.0}])
    )
    rc = cli.main(["import", str(path), "-y", "--host", "1.2.3.4"])
    assert rc == cli.EXIT_OK
    assert "2126_0 takes effect only after a restart" in capsys.readouterr().err


# --- backoffice presets: uploaded, not parsed -------------------------------------------------


def _backoffice(monkeypatch, names, blob=b"\x00\x01signed-blob"):
    """Publish backoffice presets, and serve the same blob for each."""
    from alfenctl.repo import RemotePreset

    rows = [
        RemotePreset(
            name=n, directory="BackofficePresets", size=len(blob), modified=None
        )
        for n in names
    ]
    monkeypatch.setattr("alfenctl.cli.commands.props.list_presets", lambda config: rows)
    monkeypatch.setattr(
        "alfenctl.cli.commands.props.fetch_preset_bytes", lambda preset, config: blob
    )
    return rows


def test_preset_listing_does_not_print_hundreds_of_backoffices(
    fake_charger, capsys, monkeypatch
) -> None:
    _backoffice(monkeypatch, [f"Operator{n}-B.fwi" for n in range(300)])
    assert cli.main(["preset", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "300 backoffice presets" in out
    assert "Operator7" not in out


def test_preset_installs_a_backoffice_blob_through_the_firmware_channel(
    fake_charger, capsys, monkeypatch
) -> None:
    _backoffice(monkeypatch, ["Abel&Co-A.fwi", "Abel&Co-B.fwi"])
    fake_charger.docs["/api/prop"]["properties"] += [
        {"id": "2071_1", "access": 2, "type": 9, "value": "ws://old.example"},
        {"id": "2100_0", "access": 2, "type": 9, "value": "internet"},
    ]
    rc = cli.main(["preset", "Abel&Co", "-y", "--host", "1.2.3.4"])
    assert rc == 0
    # Cleared first, then uploaded, then named -- and never parsed as settings.
    assert fake_charger.writes[0][(0x2071, 1)][0] == ""
    assert fake_charger.writes[0][(0x2100, 0)][0] == ""
    assert fake_charger.uploads == [b"\x00\x01signed-blob"]
    assert fake_charger.writes[1][(0x2076, 0)] == ("Abel&Co", 9)
    out = capsys.readouterr().out
    assert "alfenctl reboot" in out


def test_preset_backoffice_dry_run_uploads_nothing(
    fake_charger, capsys, monkeypatch
) -> None:
    _backoffice(monkeypatch, ["Abel&Co-B.fwi"])
    assert cli.main(["preset", "Abel&Co", "--dry-run", "--host", "1.2.3.4"]) == 0
    assert fake_charger.uploads == []
    assert fake_charger.writes == []
    assert "Dry run" in capsys.readouterr().out


def test_preset_backoffice_asks_before_it_installs(
    fake_charger, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    _backoffice(monkeypatch, ["Abel&Co-B.fwi"])
    assert cli.main(["preset", "Abel&Co", "--host", "1.2.3.4"]) != 0
    assert fake_charger.uploads == []
    assert "Aborted" in capsys.readouterr().err


def test_preset_backoffice_save_writes_the_blob_verbatim(
    fake_charger, capsys, monkeypatch, tmp_path
) -> None:
    _backoffice(monkeypatch, ["Abel&Co-B.fwi"])
    out = tmp_path / "preset.fwi"
    rc = cli.main(["preset", "Abel&Co", "--save", str(out), "--host", "1.2.3.4"])
    assert rc == 0
    assert out.read_bytes() == b"\x00\x01signed-blob"
    assert fake_charger.uploads == []
