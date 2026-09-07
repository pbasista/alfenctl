"""Tests for ``alfenctl tags`` -- the RFID whitelist commands."""

from __future__ import annotations

import json


from alfenctl import cli


def test_tags_list_prints_a_table(fake_charger, capsys) -> None:
    assert cli.main(["tags", "list", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "04A1B2C3" in out and "active" in out
    assert "04FFEE11" in out and "blocked" in out
    assert "2 tag(s)." in out


def test_tags_list_json(fake_charger, capsys) -> None:
    assert cli.main(["tags", "list", "--json", "--host", "1.2.3.4"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [t["tag"] for t in doc] == ["04A1B2C3", "04FFEE11"]


def test_tags_add_writes_a_full_record(fake_charger, capsys) -> None:
    assert (
        cli.main(
            [
                "tags",
                "add",
                "04DEAD01",
                "--status",
                "blocked",
                "--expires",
                "2027-01-01",
                "--host",
                "1.2.3.4",
            ]
        )
        == 0
    )
    assert fake_charger.records == [
        {"tagid": "04DEAD01", "parentid": "", "status": 2, "expire": "2027-01-01"}
    ]


def test_tags_add_rejects_a_bad_expiry(fake_charger, capsys) -> None:
    assert (
        cli.main(["tags", "add", "04AA", "--expires", "soon", "--host", "1.2.3.4"]) == 1
    )
    assert "must be YYYY-MM-DD" in capsys.readouterr().err
    assert not fake_charger.records


def test_tags_remove_and_clear(fake_charger, capsys, monkeypatch) -> None:
    assert cli.main(["tags", "remove", "04A1B2C3", "--host", "1.2.3.4"]) == 0
    assert fake_charger.verbs == ["remove=04A1B2C3"]
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(["tags", "clear", "--host", "1.2.3.4"]) == 1
    assert cli.main(["tags", "clear", "-y", "--host", "1.2.3.4"]) == 0
    assert fake_charger.verbs[-1] == "clear"


def test_tags_learn_starts_add_mode(fake_charger, capsys) -> None:
    assert cli.main(["tags", "learn", "--host", "1.2.3.4"]) == 0
    assert fake_charger.verbs == ["starttagaddmode"]
    assert "next tag presented" in capsys.readouterr().out


def test_tags_import_previews_then_applies(fake_charger, capsys, tmp_path) -> None:
    path = tmp_path / "tags.txt"
    path.write_text("04A1B2C3\n04NEW001\n")
    assert (
        cli.main(["tags", "import", str(path), "--dry-run", "--host", "1.2.3.4"]) == 0
    )
    out = capsys.readouterr().out
    assert "add    04NEW001" in out
    assert "Dry run" in out
    assert not fake_charger.records
    assert cli.main(["tags", "import", str(path), "-y", "--host", "1.2.3.4"]) == 0
    assert [r["tagid"] for r in fake_charger.records] == ["04NEW001"]


def test_tags_import_replace_removes_the_rest(fake_charger, capsys, tmp_path) -> None:
    path = tmp_path / "tags.txt"
    path.write_text("04NEW001\n")
    assert (
        cli.main(["tags", "import", str(path), "--replace", "-y", "--host", "1.2.3.4"])
        == 0
    )
    assert sorted(fake_charger.verbs) == ["remove=04A1B2C3", "remove=04FFEE11"]


def test_tags_import_without_replace_keeps_the_rest(
    fake_charger, capsys, tmp_path
) -> None:
    path = tmp_path / "tags.txt"
    path.write_text("04NEW001\n")
    assert cli.main(["tags", "import", str(path), "-y", "--host", "1.2.3.4"]) == 0
    assert not fake_charger.verbs


# --- Master tag ----------------------------------------------------------------------------


def test_tags_master_show_unsupported(fake_charger, capsys) -> None:
    assert cli.main(["tags", "master", "--host", "1.2.3.4"]) == 1
    assert "does not support a master tag" in capsys.readouterr().err


def test_tags_master_set(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += [
        {"id": "2400_1", "value": 0},
        {"id": "2400_2", "value": ""},
    ]
    assert cli.main(["tags", "master", "04AABBCC", "--host", "1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Master tag set to 04AABBCC" in out
    assert "04AABBCC (enabled)" in out


def test_tags_master_clear(fake_charger, capsys) -> None:
    fake_charger.docs["/api/prop"]["properties"] += [
        {"id": "2400_1", "value": 1},
        {"id": "2400_2", "value": "04AABBCC"},
    ]
    assert cli.main(["tags", "master", "--clear", "--host", "1.2.3.4"]) == 0
    assert "Master tag cleared." in capsys.readouterr().out
