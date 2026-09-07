"""Tests for the template check, and the run of it that guards the real UI."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "alfenctl" / "web" / "static"

_spec = importlib.util.spec_from_file_location(
    "htmcheck", ROOT / "tools" / "htmcheck.py"
)
htmcheck = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = htmcheck  # dataclasses looks the module up by name
_spec.loader.exec_module(htmcheck)


def codes(problems) -> list[str]:
    return [p.code for p in problems]


def engine():
    """One engine context carrying the vendored runtime, or a skip."""
    if htmcheck.MiniRacer is None:
        pytest.skip("mini-racer is not installed (see CONTRIBUTING.md)")
    vendor = next((ROOT / "src/alfenctl/web/static/vendor").glob("*.js"))
    ctx = htmcheck.MiniRacer()
    ctx.eval(
        htmcheck.VENDOR_EXPORT.sub(
            htmcheck.BINDINGS, vendor.read_text(encoding="utf-8")
        )
    )
    ctx.eval(htmcheck.STUBS)
    ctx.eval(htmcheck.TAP)
    ctx.eval(htmcheck.WALK)
    return ctx


def test_every_html_template_is_found_its_line_and_all_of_it() -> None:
    text = (
        "const a = html`<p>one</p>`;\n"
        "// a mention of html` in prose is not a template\n"
        "const b = html`<b>${html`<i>nested</i>`}</b>`;\n"
    )
    found = htmcheck.templates(text)
    assert [(line, "nested" in body) for line, body in found] == [(1, False), (3, True)]


def test_an_unterminated_template_is_left_for_the_parser_to_say() -> None:
    # Biome owns syntax errors; this check only walks what parses.
    assert htmcheck.templates("const a = html`<p>no end\n") == []


# --- Rendering them -------------------------------------------------------------------------


def test_an_attribute_that_lost_its_dollar_is_the_bug() -> None:
    # The shape that broke Access: an attribute interpolation missing its
    # ``$`` (``onWrite={(payload) =>``).  htm reads the value as quoted
    # text, it swallows the markup up to the next ``}``, and the tree
    # grows an element that never got a tag name -- no crash, just a
    # quietly wrong tab.
    ctx = engine()
    broken = (
        'html`<div class="grid">\n'
        "  <${Card}\n"
        "    onSave={(payload) =>\n"
        "      api\n"
        "        .post('/x', payload)\n"
        "        .then((doc) => toast.ok(doc.message))}\n"
        "  />\n"
        "</div>`"
    )
    found = htmcheck.check_file(Path("page.js"), broken, ctx)
    assert codes(found) == ["H001"]
    assert "an element without a tag name" in found[0].message


def test_an_arrow_across_lines_with_its_dollar_parses_clean() -> None:
    # The commit that fixed Access hoisted its handlers, but the
    # multiline arrow itself was never the problem: with its ``$``, the
    # interpolation is one expression and htm takes it whole.  This test
    # pins that, so the check cannot grow strict against the style.
    ctx = engine()
    wrapped = (
        'html`<div class="grid">\n'
        "  <${Card}\n"
        "    onSave=${(payload) =>\n"
        "      api\n"
        "        .post('/x', payload)\n"
        "        .then((doc) => toast.ok(doc.message))}\n"
        "  />\n"
        "</div>`"
    )
    assert htmcheck.check_file(Path("page.js"), wrapped, ctx) == []


def test_the_same_handler_hoisted_out_parses_clean() -> None:
    # The fix the bug got: keep the attribute expression simple enough
    # for the parser -- name the function above the template.
    ctx = engine()
    fixed = "html`<div>\n  <${Card} onSave=${save} />\n</div>`"
    assert htmcheck.check_file(Path("page.js"), fixed, ctx) == []


def test_a_template_needs_nothing_but_itself_to_parse() -> None:
    # Props, imports, helpers: every free identifier is stubbed, because
    # the parse happens before any of them is looked up.
    ctx = engine()
    ordinary = (
        "html`<section class=${cls}>\n"
        "  <${Panel} title=${title} rows=${rows} onPick=${pick} />\n"
        "  ${rows.map((row) => html`<b key=${row.id}>${row.label}</b>`)}\n"
        "</section>`"
    )
    assert htmcheck.check_file(Path("page.js"), ordinary, ctx) == []


def test_plain_text_that_merely_contains_no_code_stays_clean() -> None:
    ctx = engine()
    prose = "html`<p>100 % charged, and {no} code to see</p>`"
    assert htmcheck.check_file(Path("page.js"), prose, ctx) == []


def test_a_template_built_inside_a_callback_is_checked_too() -> None:
    # Most of this UI's markup is written inside a callback, and a stub
    # that only returned itself never called one -- so the check stopped
    # at the first `.map` and every row behind it was reported clean.
    ctx = engine()
    broken = (
        "html`<div>\n"
        "  ${rows.map((r) => html`<${Card}\n"
        "    onSave={(payload) =>\n"
        "      api\n"
        "        .post('/x', payload)\n"
        "        .then((doc) => toast.ok(doc.message))}\n"
        "  />`)}\n"
        "</div>`"
    )
    assert codes(htmcheck.check_file(Path("page.js"), broken, ctx)) == ["H001"]


def test_a_callback_that_returns_plain_data_is_not_an_element() -> None:
    # Calling the callbacks means the check sees what they return, and
    # what a `.map` for a select returns is a list of `{value, title}` --
    # data, not an element that lost its tag name.
    ctx = engine()
    ordinary = (
        "html`<${Select}\n"
        "  entries=${sockets.map((n) => ({ value: String(n), title: `socket ${n}` }))}\n"
        "/>`"
    )
    assert htmcheck.check_file(Path("page.js"), ordinary, ctx) == []


# --- Comments that are not comments ---------------------------------------------------------


def test_a_comment_written_inside_a_template_is_text_the_page_shows() -> None:
    # Markup has no comments.  htm keeps this one as a text node and the
    # user reads it in the middle of the card.  This shipped once in a
    # draft of the Console card and the check said nothing.
    ctx = engine()
    commented = (
        "html`<${Card} title='Console'>\n"
        "  /* the command list is what decides the width */\n"
        "  <button>Go</button>\n"
        "</${Card}>`"
    )
    found = htmcheck.check_file(Path("page.js"), commented, ctx)
    assert codes(found) == ["H004"]
    assert "the command list is what decides the width" in found[0].message


def test_a_line_comment_inside_a_template_is_text_as_well() -> None:
    ctx = engine()
    commented = "html`<div>\n  // one day this gets a spinner\n  <b>hi</b>\n</div>`"
    assert codes(htmcheck.check_file(Path("page.js"), commented, ctx)) == ["H004"]


def test_a_comment_is_reported_at_the_line_it_sits_on() -> None:
    # The template's own line is where a mis-parse is reported, because a
    # mis-parse is the whole template's problem.  A comment is one place.
    ctx = engine()
    text = "const x = 1;\n\nconst card = html`<div>\n  <b>hi</b>\n  /* stray */\n</div>`;\n"
    found = htmcheck.check_file(Path("page.js"), text, ctx)
    assert [(p.line, p.code) for p in found] == [(5, "H004")]


def test_a_comment_inside_an_interpolation_is_a_real_comment() -> None:
    # `${...}` is JavaScript, where a comment is a comment: only the
    # statics -- the markup around them -- are read for this.
    ctx = engine()
    fine = (
        "html`<div>${rows.map((row) => {\n"
        "  /* one line per socket, in the order the charger gave them */\n"
        "  return html`<b>${row}</b>`;\n"
        "})}</div>`"
    )
    assert htmcheck.check_file(Path("page.js"), fine, ctx) == []


def test_a_url_in_the_markup_is_not_a_comment() -> None:
    # The `//` in every URL, and a path built onto an interpolation.
    ctx = engine()
    urls = (
        "html`<p>\n"
        "  see <a href='https://example.com/a//b'>the manual</a>,\n"
        "  or <a href=${base}//deep/link>this</a>\n"
        "</p>`"
    )
    assert htmcheck.check_file(Path("page.js"), urls, ctx) == []


def test_a_comment_inside_a_nested_template_is_found_too() -> None:
    ctx = engine()
    nested = (
        "html`<div>${items.map((i) => html`<b>\n  /* inner */\n  ${i}</b>`)}</div>`"
    )
    assert codes(htmcheck.check_file(Path("page.js"), nested, ctx)) == ["H004"]


# --- The real thing -------------------------------------------------------------------------


def test_the_web_ui_passes_its_own_template_check() -> None:
    if htmcheck.MiniRacer is None:
        pytest.skip("mini-racer is not installed (see CONTRIBUTING.md)")
    problems = htmcheck.check_tree(STATIC)
    assert not problems, "\n".join(p.render(ROOT) for p in problems)


def test_a_tree_with_no_vendored_runtime_says_so() -> None:
    if htmcheck.MiniRacer is None:
        pytest.skip("mini-racer is not installed (see CONTRIBUTING.md)")
    empty = Path("/nonexistent-tree")
    found = htmcheck.check_tree(empty)
    assert codes(found) == ["H003"]
