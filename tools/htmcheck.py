#!/usr/bin/env python3
"""Render every ``html`` template in the web UI, and report what mis-parses.

The templates are tagged-template literals driven through the vendored
preact-htm bundle -- the same code the browser runs -- so this check needs
no browser and no build step, only a small JavaScript engine.  It exists
because of a bug class no static check can see.  An attribute expression
that has lost its ``$`` -- ``onWrite={(payload) =>`` -- is read by htm as
a quoted value whose text then swallows the markup up to the next ``}``;
the page does not crash, the tab is just quietly wrong: elements without
tag names, a handler's source rendered as prose.  Something like this
shipped once, and neither Biome nor the wiring checks saw anything.

So that is the check: evaluate each template through the real parser with
every free identifier stubbed, then walk the resulting virtual DOM and
report the one shape no valid output contains -- an element whose type is
``undefined``, its tag name consumed as text (``H001``).  The stubs cannot
hide a mis-parse: parsing happens in the template's statics, before any
value is ever looked up, so anything that renders cleanly under stubs
parses cleanly in the browser.

The parser is also what says where the markup ends, which catches a
second mistake that renders rather than crashing.  A template is markup,
not code, and markup has no comments: a ``/* ... */`` written inside one
is not stripped by anything -- htm keeps it as text and the page shows it
to the user, in the middle of a card (``H004``).  The tag is wrapped on
the way in so each template's statics -- its markup, everything that is
not a ``${...}`` -- can be read as it parses, which is what keeps a real
comment inside an interpolation from being mistaken for one.

The engine is PyMiniRacer (``pip install mini-racer``): an embedded V8
brought in as one pure-Python wheel with the engine bundled, so no Node,
no npm, and nothing to compile.  It is a dev dependency of the project
rather than of the program, and the check skips when it is not installed.
Run it directly (``python tools/htmcheck.py``) or let pytest do it; either
way a problem is one line of ``path:line: CODE message``.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from py_mini_racer import MiniRacer
except ImportError:  # the engine is a tool, not a dependency (see Biome)
    MiniRacer = None  # type: ignore[assignment]

# The vendor bundle's single export statement names the minified locals it
# binds; htm's ``html`` is the tag this check drives.  Replacing the export
# with plain ``var`` bindings makes the bundle evaluable as a script, which
# is the only way to load it in an engine without ES modules.
VENDOR_EXPORT = re.compile(r"export\{[^}]*\};?\s*$")
BINDINGS = "var h = a, html = fe, render = M;"

# What every template may reference without naming it: the language's own
# words and globals.  Everything else is a free identifier -- a prop, an
# import, a helper -- and gets a stub, because the parse happens before any
# of them is ever looked up.
RESERVED = frozenset(
    """
    break case catch class const continue debugger default delete do else
    export extends finally for function if import in instanceof new return
    super switch this throw try typeof var void while with yield let static
    enum await implements package protected interface private public
    arguments eval true false null undefined
    """.split()
)
ENGINE_GLOBALS = frozenset(
    """
    h html render Math JSON String Number Array Object Boolean Symbol Proxy
    Map Set Date RegExp Error isNaN parseInt parseFloat console window
    document globalThis
    """.split()
)
IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")

# What a template is not: ``html`` in prose (a comment) or in a string.
# Their interiors are blanked before the search, same length so the line
# numbers survive; template literals are left alone, because one template
# inside another's interpolation is code, not prose.
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_QUOTED = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"")


def _blanked(text: str) -> str:
    """Replace comment and string interiors with spaces, keeping the shape."""

    def blanks(match: re.Match[str]) -> str:
        whole = match.group(0)
        return whole[0] + " " * (len(whole) - 2) + whole[-1]

    out = _COMMENT.sub(lambda m: " " * len(m.group(0)), text)
    return _QUOTED.sub(blanks, out)


def templates(text: str) -> list[tuple[int, str]]:
    """Find every ``html`...``` template and the line it starts on.

    The scan for openers runs over the blanked text, so a mention in
    prose is not a template; the span then comes from the real text,
    brace-aware -- a backtick inside ``${...}`` belongs to a nested
    template -- because half the UI nests one template inside another's
    interpolations.
    """
    where = _blanked(text)
    found: list[tuple[int, str]] = []
    start = 0
    while True:
        at = where.find("html`", start)
        if at < 0:
            return found
        line = text.count("\n", 0, at) + 1
        i = at + len("html`")
        depth = 0
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == "`" and depth == 0:
                break
            i += 1
        if i >= len(text):  # an unterminated template: biome's to say, not ours
            start = at + 5
            continue
        found.append((line, text[at : i + 1]))
        start = i + 1


# A stub stands in for whatever the template is tooled against: call it,
# read any property, iterate it, spread it -- none of that is this check's
# business, and none of it can hide a mis-parse, which happens in the
# statics before any value is touched.
#
# With one thing it does have to do: call the functions it is handed.  Most
# of this UI's markup is written inside a callback -- ``${rows.map((row) =>
# html`...`)}`` -- and a callback nobody calls is a template nobody parses.
# A stub that only returned itself stopped the check at the first ``.map``,
# so a card whose rows were built that way was reported clean whatever was
# wrong with them.  What the call itself does is still not this check's
# business, so what it throws is dropped: the parse the check came for has
# already happened by then.  Nor does the markup a callback builds have to
# come back out of it -- a stub still hands its caller a stub rather than
# the mapped array, and every template reports itself to the tap instead.
STUBS = """
var depth = 0;
function stubFor() {
  const stub = new Proxy(function () {}, {
    get(target, key) {
      if (key === Symbol.iterator) return function* () {};
      if (key === 'length') return 0;
      if (key === Symbol.toPrimitive) return () => 'stub';
      return stub;
    },
    apply(target, self, args) {
      for (const arg of args) {
        if (typeof arg !== 'function' || depth > 8) continue;
        depth += 1;
        try { arg(stubFor(), 0, stubFor()); } catch (err) {} finally { depth -= 1; }
      }
      return stub;
    },
    has() { return true; },
  });
  return stub;
}
"""


# The vendored tag, wrapped so the check can read both what it was handed
# and what it made of it.  A tagged template's ``strings.raw`` is its
# statics: the markup, split at the interpolations, exactly as written.
#
# Every template reports itself here, nested ones included, which is what
# makes a template built inside a callback checkable at all -- its result
# is walked from this list rather than from the tree, because the stub
# that called the callback threw the return value away.
TAP = """
function tapped(seen, built) {
  return function (strings) {
    const raw = strings.raw || strings;
    for (const part of raw) seen.push(part);
    const out = html.apply(null, arguments);
    built.push(out);
    return out;
  };
}
"""


# The one shape a mis-parsed template reliably leaves behind: something in
# the output with no ``type``.  That is htm's own half-built ``[tag, props,
# ...]`` coming back whole rather than being made into an element, so what
# the walk actually meets is the bare props object; a template that parsed
# hands back elements, whose type is always a tag name or a component.
#
# It is only ever given a template's own output -- every result the tap
# collected -- because a plain object is only wrong where an element was
# meant.  One returned from a ``.map`` that builds a select's entries is
# data, and reading the rule onto those would condemn half the UI.
WALK = """
function walk(node, issues) {
  if (node == null || node === undefined) return;
  if (Array.isArray(node)) { node.forEach((child) => walk(child, issues)); return; }
  if (typeof node !== 'object') return;
  if (node.type === undefined) issues.push('an element without a tag name');
  const kids = node.props && node.props.children;
  if (kids != null) walk(kids, issues);
}
"""


# Comment-shaped text in a template's markup.  A block comment is reported
# wherever it sits, because nothing else in this UI's markup is written
# ``/* ... */``.  A line comment is only reported when it starts a line: a
# static can begin mid-line, just after an interpolation, and ``${base}//x``
# is a path, not a comment -- as is the ``//`` in every URL.
MARKUP_COMMENT = (
    re.compile(r"/\*.*?\*/", re.S),
    re.compile(r"\n[ \t]*//[^\n]*"),
)


def markup_comments(statics: list[str]) -> list[str]:
    """Find the comment-shaped text a template would render, in order."""
    return [
        match.group(0).strip()
        for static in statics
        for pattern in MARKUP_COMMENT
        for match in pattern.finditer(static)
    ]


@dataclass(frozen=True)
class Problem:
    """One thing wrong, at one place, in the words a reader needs."""

    path: Path
    line: int
    code: str
    message: str

    def render(self, root: Path) -> str:
        """One line of ``path:line: CODE message``, relative to the root."""
        where = (
            self.path.relative_to(root) if self.path.is_relative_to(root) else self.path
        )
        return f"{where}:{self.line}: {self.code} {self.message}"


def check_file(path: Path, text: str, engine) -> list[Problem]:
    """Evaluate one module's templates through the vendored parser."""
    found: list[Problem] = []
    for line, template in templates(text):
        # Every identifier the template names becomes a parameter, every
        # parameter a stub: the parse runs to completion no matter what the
        # component was tooled against.
        names = sorted(set(IDENTIFIER.findall(template)) - RESERVED - ENGINE_GLOBALS)
        params = ", ".join(names)
        args = ", ".join("stubFor()" for _ in names)
        wrapped = (
            f"(function ({params}) {{ var __seen = [], __built = []; "
            f"var html = tapped(__seen, __built); "
            f"var threw = null; "
            f"try {{ {template}; }} catch (err) {{ threw = String(err); }} "
            f"var issues = []; walk(__built, issues); "
            f"if (threw !== null) issues = [threw]; "
            f"issues = issues.filter(function (m, i) {{ return issues.indexOf(m) === i; }}); "
            f"return JSON.stringify({{ issues: issues, statics: __seen }}); }})({args})"
        )
        try:
            report = str(engine.eval(wrapped))
        except Exception as err:  # the engine refused the wrapper itself
            found.append(Problem(path, line, "H002", f"could not be evaluated: {err}"))
            continue
        issues, statics = read_report(report)
        if issues:
            found.append(Problem(path, line, "H001", "; ".join(issues)))
        # A template that never parsed has no markup to read; whatever the
        # statics hold, the mis-parse above is the thing to fix first.
        for comment in [] if issues else markup_comments(statics):
            found.append(
                Problem(
                    path,
                    line + template.count("\n", 0, max(template.find(comment), 0)),
                    "H004",
                    f"a comment inside the template, which the page shows as "
                    f"text: {shorten(comment)}",
                )
            )
    return found


def shorten(text: str, width: int = 60) -> str:
    """One line of it, enough to find it by."""
    one = " ".join(text.split())
    return one if len(one) <= width else f"{one[: width - 3]}..."


def read_report(report: str) -> tuple[list[str], list[str]]:
    """Read back the run's findings; a malformed report is its own finding."""
    import json

    try:
        doc = json.loads(report)
        return [str(item) for item in doc["issues"]], [
            str(part) for part in doc["statics"]
        ]
    except (ValueError, KeyError, TypeError):
        return [f"unreportable: {report[:100]}"], []


def check_tree(root: Path) -> list[Problem]:
    """Check every module under ``js/`` against the vendored parser."""
    if MiniRacer is None:
        print("htmcheck: mini-racer is not installed; nothing was checked")
        return []
    vendor = next(root.glob("vendor/*.js"), None)
    if vendor is None:
        return [Problem(root, 0, "H003", "no vendored runtime under vendor/")]
    engine = MiniRacer()
    engine.eval(VENDOR_EXPORT.sub(BINDINGS, vendor.read_text(encoding="utf-8")))
    engine.eval(STUBS)
    engine.eval(TAP)
    engine.eval(WALK)
    found: list[Problem] = []
    for path in sorted(root.glob("js/*.js")):
        found += check_file(path, path.read_text(encoding="utf-8"), engine)
    return found


def main(argv: list[str] | None = None) -> int:
    """Check the tree named on the command line, or the UI's own."""
    if MiniRacer is None:
        print(
            "htmcheck: mini-racer is not installed (pip install mini-racer); skipping"
        )
        return 0
    args = list(sys.argv[1:] if argv is None else argv)
    here = Path(__file__).resolve().parent.parent
    root = Path(args[0]) if args else here / "src" / "alfenctl" / "web" / "static"
    problems = check_tree(root)
    for problem in problems:
        print(problem.render(root.parent))
    print(
        f"htmcheck: {len(problems)} problem(s) in {root}"
        if problems
        else f"htmcheck: clean ({root})"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
