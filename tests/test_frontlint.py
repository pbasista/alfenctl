"""Tests for the frontend linter, and the runs of it that guard the real UI."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "alfenctl" / "web" / "static"

_spec = importlib.util.spec_from_file_location(
    "frontlint", ROOT / "tools" / "frontlint.py"
)
frontlint = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = frontlint  # dataclasses looks the module up by name
_spec.loader.exec_module(frontlint)


def codes(problems) -> list[str]:
    return [p.code for p in problems]


# --- Style --------------------------------------------------------------------------------


def test_the_classes_a_stylesheet_defines() -> None:
    found = frontlint.css_classes(".pill.on > .dot,\n.card { margin: 0.5em; }\n")
    assert found == {"pill": 1, "on": 1, "dot": 1, "card": 2}


def test_a_rule_nothing_uses_is_dead() -> None:
    styles = {Path("app.css"): ".live { color: red; }\n.gone { color: blue; }\n"}
    users = {Path("app.js"): 'html`<p class="live"></p>`;\n'}
    found = frontlint.check_style_use(
        [Path("app.css")], {**styles, **users}, [Path("app.js")]
    )
    assert [(p.code, p.line) for p in found] == [("C002", 2)]
    assert ".gone is used by nothing" in found[0].message


def test_a_class_only_assembled_at_run_time_counts_as_used() -> None:
    # `` `pill ${state}` `` never writes "warn" into markup, but the name is
    # there in the module, and that is all this check asks for.
    styles = {Path("app.css"): ".warn { color: amber; }\n"}
    users = {Path("app.js"): "const cls = `pill ${bad ? 'warn' : 'ok'}`;\n"}
    assert (
        frontlint.check_style_use(
            [Path("app.css")], {**styles, **users}, [Path("app.js")]
        )
        == []
    )


def test_a_class_nothing_defines_is_a_problem() -> None:
    # The failure this check exists for: a dialog wearing `modal-backdrop`,
    # which no stylesheet ever defined, so it rendered as a plain block.
    styles = {Path("app.css"): ".modal { position: fixed; }\n"}
    users = {
        Path("app.js"): 'html`<div class="modal-backdrop">\n  <div class="modal">`;\n'
    }
    found = frontlint.check_style_defined(
        [Path("app.css")], {**styles, **users}, [Path("app.js")]
    )
    assert [(p.code, p.line) for p in found] == [("C003", 1)]
    assert "modal-backdrop" in found[0].message


def test_a_class_assembled_at_run_time_is_not_held_to_a_stylesheet() -> None:
    # `class=${`pill ${state}`}` is not a literal attribute, so it is not
    # this check's business -- the same generosity C002 shows in reverse.
    styles = {Path("app.css"): ".pill { color: red; }\n"}
    users = {Path("app.js"): "html`<span class=${`pill ${state}`}></span>`;\n"}
    assert (
        frontlint.check_style_defined(
            [Path("app.css")], {**styles, **users}, [Path("app.js")]
        )
        == []
    )


def test_every_class_in_a_literal_attribute_is_checked() -> None:
    styles = {Path("app.css"): ".btn { border: 0; }\n"}
    users = {Path("app.js"): 'html`<button class="btn ghost small">`;\n'}
    found = frontlint.check_style_defined(
        [Path("app.css")], {**styles, **users}, [Path("app.js")]
    )
    assert sorted(p.message.split()[0] for p in found) == [".ghost", ".small"]


def test_a_rule_marked_keep_is_left_alone() -> None:

    styles = {Path("app.css"): ".unseen { color: red; } /* frontlint: keep */\n"}
    assert frontlint.check_style_use([Path("app.css")], styles, []) == []


# --- Wiring -------------------------------------------------------------------------------


def wiring(tmp_path: Path, files: dict[str, str]) -> list:
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    scripts = sorted(tmp_path / name for name in files if name.endswith(".js"))
    sources = {path: path.read_text(encoding="utf-8") for path in scripts}
    return frontlint.check_wiring(scripts, sources)


def test_an_import_of_a_module_that_is_not_there(tmp_path: Path) -> None:
    found = wiring(tmp_path, {"app.js": "import { fmt } from './missing.js';\n"})
    assert codes(found) == ["J003"]
    assert "no such module: ./missing.js" in found[0].message


def test_an_import_of_a_name_the_module_does_not_export(tmp_path: Path) -> None:
    found = wiring(
        tmp_path,
        {
            "app.js": "import { fmt, pad } from './ui.js';\nfmt(pad(1));\n",
            "ui.js": "export function fmt(v) { return v; }\n",
        },
    )
    assert codes(found) == ["J004"]
    assert "./ui.js does not export pad" in found[0].message


def test_an_export_nobody_imports(tmp_path: Path) -> None:
    found = wiring(
        tmp_path,
        {
            "app.js": "import { fmt } from './ui.js';\nfmt(1);\n",
            "ui.js": "export function fmt(v) { return v; }\nexport function pad(v) { return v; }\n",
        },
    )
    assert [(p.code, p.line) for p in found] == [("J005", 2)]
    assert "pad is exported but never imported" in found[0].message


def test_the_entry_module_answers_to_the_page_not_to_an_import(tmp_path: Path) -> None:
    assert wiring(tmp_path, {"app.js": "export function boot() { return 1; }\n"}) == []


def test_a_star_import_takes_everything(tmp_path: Path) -> None:
    assert (
        wiring(
            tmp_path,
            {
                "app.js": "import * as ui from './ui.js';\nui.fmt(1);\n",
                "ui.js": "export function fmt(v) { return v; }\n",
            },
        )
        == []
    )


# --- The runtime's names -------------------------------------------------------------------


def runtime_names(tmp_path: Path, files: dict[str, str]) -> list:
    """Run check_runtime_names against a fake tree with a fake vendor."""
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    scripts = sorted(tmp_path / name for name in files if name.endswith(".js"))
    sources = {path: path.read_text(encoding="utf-8") for path in scripts}
    vendor = tmp_path / "vendor.js"
    return frontlint.check_runtime_names(scripts, sources, vendor)


def test_a_hook_used_without_its_import(tmp_path: Path) -> None:
    # The properties.js bug: the import line was lost in a refactor and the
    # tab went quietly blank -- the component throws mid-render and the
    # page keeps whatever it showed before.
    found = runtime_names(
        tmp_path,
        {
            "vendor.js": "export{a as h,b as html,c as useState,d as useEffect};\n",
            "page.js": "export const Tab = () => {\n  const [x, setX] = useState(0);\n  return html`<b>${x}</b>`;\n};\n",
        },
    )
    assert codes(found) == ["J006", "J006"]
    assert "useState is used but not imported" in found[0].message
    assert "html is used but not imported" in found[1].message


def test_the_runtime_names_with_their_import_present(tmp_path: Path) -> None:
    found = runtime_names(
        tmp_path,
        {
            "vendor.js": "export{a as h,b as html,c as useState};\n",
            "page.js": (
                "import { html, useState } from './vendor.js';\n"
                "export const Tab = () => html`<b>${useState(0)}</b>`;\n"
            ),
        },
    )
    assert found == []


def test_the_runtime_names_bound_any_other_way(tmp_path: Path) -> None:
    # A local of its own, an aliased import, a star import, a parameter
    # that shadows the name -- all bind it, and none is this check's business.
    found = runtime_names(
        tmp_path,
        {
            "vendor.js": "export{a as html,b as useState,c as render};\n",
            "page.js": (
                "import { useState as useVal } from './vendor.js';\n"
                "import * as preact from './other.js';\n"
                "const render = (v) => v;\n"
                "export const f = ([k, v, html]) => html(v);\n"
                "export const g = () => useVal(0) + preact.html;\n"
            ),
        },
    )
    assert found == []


def test_a_mention_that_is_not_a_use_stays_silent(tmp_path: Path) -> None:
    # A comment, an object key, a word in a template literal: none of them
    # reach the runtime as the vendor's name.
    found = runtime_names(
        tmp_path,
        {
            "vendor.js": "export{a as h,b as html,c as useState};\n",
            "page.js": (
                "import { html } from './vendor.js';\n"
                "// useState would be shorter\n"
                "const key = { html: 1 };\n"
                "export const x = () => html`${(1 / 2).toFixed(1)} h`;\n"
            ),
        },
    )
    assert found == []


def test_a_page_that_asks_for_a_file_that_is_not_there(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<link rel="stylesheet" href="app.css">\n'
        '<script type="module" src="js/app.js"></script>\n'
        '<link rel="icon" href="https://example.invalid/i.png">\n'
        '<body class="a"></body>\n',
        encoding="utf-8",
    )
    (tmp_path / "app.css").write_text(".a { color: red; }\n", encoding="utf-8")
    found = frontlint.check_tree(tmp_path)
    assert [(p.code, p.line) for p in found] == [("H001", 2)]
    assert "no such file: js/app.js" in found[0].message  # the absolute URL is not ours


# --- Operation names ----------------------------------------------------------------------

API = """
def read_log(ctx):
    if since:
        return ctx.worker.run(f"Reading the event log since {since}", back)
    return ctx.worker.run("Reading the event log", read)


def read_properties(ctx):
    name = f"Reading properties ({category})" if category else "Reading all properties"
    return ctx.worker.run(name, collect)


def read_sessions(ctx):
    return ctx.worker.run("Reading charging sessions", read)
"""
"""A stand-in for web/api.py: the three shapes a name reaches the link in.

Written at the call, grown from an f-string, and chosen into a local before
the call -- the properties read does the last of those.
"""


def lint_against_api(tmp_path: Path, panel: str):
    """Lint a one-module tree whose server half is the fake API above."""
    static = tmp_path / "static"
    (static / "js").mkdir(parents=True)
    (tmp_path / "api.py").write_text(API, encoding="utf-8")
    (static / "js" / "app.js").write_text(panel, encoding="utf-8")
    return [p for p in frontlint.check_tree(static) if p.code == "C004"]


def test_the_names_an_api_publishes_include_the_ones_it_picks_first() -> None:
    assert frontlint.operation_names(API) == {
        "Reading the event log since ",
        "Reading the event log",
        "Reading properties (",
        "Reading all properties",
        "Reading charging sessions",
    }


def test_a_progress_bar_waiting_on_a_name_nobody_publishes(tmp_path: Path) -> None:
    # The transactions bug, exactly: one extra word and the bar never draws.
    found = lint_against_api(
        tmp_path,
        'html`<${Progress} link=${link} what="Reading the charging sessions" />`;\n',
    )
    assert [p.code for p in found] == ["C004"]
    assert "never draws" in found[0].message


def test_a_progress_bar_whose_name_catches_everybody_elses_reads(
    tmp_path: Path,
) -> None:
    # The properties bug: a prefix short enough to match unrelated reads.
    found = lint_against_api(
        tmp_path, 'html`<${Progress} link=${link} what="Reading" />`;\n'
    )
    assert [p.code for p in found] == ["C004"]
    assert "other panels' reads" in found[0].message


def test_one_operation_under_several_names_is_one_operation(tmp_path: Path) -> None:
    # "Reading the event log" and "... since 7d" are one read, so naming the
    # shorter of them is right rather than over-broad.
    assert not lint_against_api(
        tmp_path, 'html`<${Progress} link=${link} what="Reading the event log" />`;\n'
    )


def test_a_panel_may_name_every_operation_it_waits_on(tmp_path: Path) -> None:
    assert not lint_against_api(
        tmp_path,
        "html`<${Progress} link=${link} "
        "what=${['Reading all properties', 'Reading properties']} />`;\n",
    )


# --- What a card claims -------------------------------------------------------------------


def lint_widths(tmp_path: Path, module: str):
    """Lint a one-module tree and return just the card-width reports."""
    (tmp_path / "js").mkdir(parents=True)
    (tmp_path / "js" / "app.js").write_text(module, encoding="utf-8")
    return [p for p in frontlint.check_tree(tmp_path) if p.code == "C005"]


def test_a_short_card_may_not_claim_the_whole_row(tmp_path: Path) -> None:
    found = lint_widths(
        tmp_path,
        "function Firmware() {\n"
        '  return html`<${Card} title="Firmware" width="full">\n'
        "    <div>${releases.map((r) => html`<p>${r.name}</p>`)}</div>\n"
        "  <//>`;\n"
        "}\n",
    )
    assert [p.code for p in found] == ["C005"]
    assert "ends the row" in found[0].message
    assert "table, log or plot" in found[0].message


def test_a_table_earns_the_row(tmp_path: Path) -> None:
    assert not lint_widths(
        tmp_path,
        "function MeterMap() {\n"
        '  return html`<${Card} title="Custom meter map" width="full">\n'
        "    <table><tbody>${rows}</tbody></table>\n"
        "  <//>`;\n"
        "}\n",
    )


def test_a_plot_earns_the_row(tmp_path: Path) -> None:
    # A chart is drawn to the width it is given, and one bar per day over a
    # year of charging wants the row as much as any table does.
    assert not lint_widths(
        tmp_path,
        "function EnergyChart() {\n"
        '  return html`<${Card} title="Energy delivered, by day" width="full">\n'
        '    <svg viewBox="0 0 720 150">${bars}</svg>\n'
        "  <//>`;\n"
        "}\n",
    )


def test_the_table_has_to_be_in_the_card_that_claims_the_row(tmp_path: Path) -> None:
    # Two components in one module: the table belongs to the first, so it
    # does not excuse the second.
    found = lint_widths(
        tmp_path,
        "function MeterTest() {\n"
        "  return html`<${Card}><table></table><//>`;\n"
        "}\n"
        "\n"
        "function WifiScan() {\n"
        '  return html`<${Card} width="full"><p>${ssid}</p><//>`;\n'
        "}\n",
    )
    assert [(p.code, p.line) for p in found] == [("C005", 6)]


def test_a_width_that_follows_the_content_is_not_asked(tmp_path: Path) -> None:
    # `width=${open ? 'full' : undefined}` is the card answering for itself.
    assert not lint_widths(
        tmp_path,
        "function Console() {\n"
        "  return html`<${Card} width=${open ? 'full' : undefined}><p>x</p><//>`;\n"
        "}\n",
    )


# --- The real thing -----------------------------------------------------------------------


def test_the_web_ui_passes_its_own_linter() -> None:
    problems = frontlint.check_tree(STATIC)
    assert not problems, "\n".join(p.render(ROOT) for p in problems)


def test_the_web_ui_passes_biome() -> None:
    """Biome does the parsing and the rules; this is the same run CI makes.

    It is a single native binary and there is no Node here, so it is not a
    project dependency and may simply be absent: `biome.json` says what it
    checks, and the CI job installs it and runs it in its own right.
    """
    biome = shutil.which("biome")
    if biome is None:
        pytest.skip("biome is not installed (see biome.json and the CI workflow)")
    done = subprocess.run([biome, "ci"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
