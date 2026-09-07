#!/usr/bin/env python3
"""The checks the web UI needs that no off-the-shelf linter does.

Biome (``biome.json``) parses and lints the browser half: syntax, the
recommended rule set, CSS, and the one page.  It is better at all of that
than anything hand-written here could be.  What it does not do -- what no
JavaScript linter does, because it is normally a bundler's job -- is look
across the files:

* **Wiring.**  Every ``import`` has to name a file that exists and a name
  that file exports, and every ``export`` has to be imported by somebody.
  There is no build step here: the modules are served to the browser as
  they are on disk and only meet each other at run time, so a mistyped
  path or export name is a blank page found by reloading, and not before.
* **What a card is allowed to claim.**  A full-width card ends its row, so
  one that spans the grid without a row's worth of content stacks the
  whole tab underneath it.  The stylesheet says which content earns it;
  nothing but a reader was checking.
* **Operation names.**  A progress bar draws only while the operation the
  server published matches the name the panel is waiting for -- one string
  written in ``web/api.py`` and again, in another language, in a
  ``what=`` prop.  Nothing else can see both halves, so a rename turns a
  bar off silently and no test fails.
* **The runtime's names.**  A module that calls ``useState`` or tags a
  template with ``html`` without importing it from the vendored module is
  a component that renders nothing -- the import is a run-time question,
  so no bundler ever gets to answer it.  The names the vendor exports
  are therefore checked like the wiring: used means imported.

That is the whole of it, and it is meant to stay that way: anything a
general JavaScript or CSS linter can check belongs in ``biome.json``, not
here.  Run it directly (``python tools/frontlint.py``) or let ``pytest``
do it; either way a problem is one line of ``path:line: CODE message``.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# The module every other one is reachable from; its exports answer to the
# page, not to an import.
ENTRY_MODULE = "app.js"

# Files under here are somebody else's and are checked by nobody.
VENDOR = "vendor"

# Written on a rule whose class is only ever assembled at run time -- a log
# level, a job state -- which this checker has no way of seeing.
KEEP = "frontlint: keep"

IMPORT_NAMED = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")
IMPORT_STAR = re.compile(r"import\s*\*\s*as\s*(\w+)\s*from\s*['\"]([^'\"]+)['\"]")
IMPORT_ANY = re.compile(r"^\s*import\b[^;]*from\s*['\"]([^'\"]+)['\"]", re.M)
IMPORT_NAMES = re.compile(r"import\s*\{([^}]*)\}", re.S)
EXPORTED = re.compile(
    r"^export\s+(?:async\s+)?(?:function|const|let|var|class)\s+(\w+)", re.M
)
HTML_ASSET = re.compile(r"(?:src|href)=\"([^\"]+)\"")


# What a module can take from the vendored preact-htm bundle.  A name used
# without its import is a ReferenceError that kills the component mid-render,
# so the page keeps whatever it last showed -- found, if at all, by hand.

VENDOR_EXPORT = re.compile(r"export\{([^}]*)\}")
VENDOR_NAME = re.compile(r"([a-zA-Z_$][\w$]*)\s+as\s+([a-zA-Z_$][\w$]*)")
# The shapes that mean "this identifier really is the runtime's": a hook or
# factory call, a tagged template, a component base class.  A bare mention
# (a comment, an object key) is not.  The scan runs over the code with its
# string and template interiors blanked out, so an ``h`` at the end of a
# literal and an ``html`` in a comment are never in these shapes at all.
RUNTIME_USE = {
    "call": re.compile(r"(?<![\w$.])(\w+)\s*\("),
    "tag": re.compile(r"(?<![\w$.])(\w+)\s*`"),
    "extends": re.compile(r"\bextends\s+(\w+)"),
}

# ``'text'``, ``"text"``, ```text` `` and their ``\`` escapes, replaced by
# their quotes alone so line numbers survive.  Comments too: /* */ and //.
_STR = re.compile(r"(\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`)")
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def _blank_strings_and_comments(text: str) -> str:
    """Blank out the interiors of strings, templates and comments."""
    out = _COMMENT.sub(lambda m: " " * len(m.group(0)), text)
    out = _STR.sub(
        lambda m: m.group(0)[0] + " " * (len(m.group(0)) - 2) + m.group(0)[-1], out
    )
    return out


@dataclass(frozen=True)
class Problem:
    """One thing wrong, at one place, in the words a reader needs."""

    path: Path
    line: int
    code: str
    message: str

    def render(self, root: Path) -> str:
        """Format as an editor-clickable line."""
        try:
            where = self.path.relative_to(root)
        except ValueError:  # pragma: no cover - only if given an outside path
            where = self.path
        return f"{where}:{self.line}: {self.code} {self.message}"


def _line_of(text: str, index: int) -> int:
    """Return the 1-based line number of a character offset."""
    return text.count("\n", 0, index) + 1


def _blank_css(text: str) -> str:
    """Return the stylesheet with its comments replaced by spaces."""
    out = list(text)
    for match in re.finditer(r"/\*.*?\*/", text, re.S):
        for index in range(*match.span()):
            if out[index] != "\n":
                out[index] = " "
    return "".join(out)


def css_classes(text: str) -> dict[str, int]:
    """Return every class the stylesheet defines, with the line it is on."""
    blanked = _blank_css(text)
    classes: dict[str, int] = {}
    for match in re.finditer(r"\.(-?[_a-zA-Z][\w-]*)", blanked):
        # A class in a selector, not `0.5` or a file extension in a url().
        classes.setdefault(match.group(1), _line_of(text, match.start()))
    return classes


def check_tree(root: Path) -> list[Problem]:
    """Check the whole static tree: the wiring, the style, the page."""
    scripts = sorted(p for p in root.rglob("*.js") if VENDOR not in p.parts)
    styles = sorted(p for p in root.rglob("*.css") if VENDOR not in p.parts)
    pages = sorted(p for p in root.rglob("*.html") if VENDOR not in p.parts)
    sources = {
        path: path.read_text(encoding="utf-8") for path in scripts + styles + pages
    }

    found: list[Problem] = []
    for path in pages:
        for match in HTML_ASSET.finditer(sources[path]):
            target = match.group(1)
            if target.startswith(("http:", "https:", "data:", "#", "//")):
                continue
            if not (path.parent / target.lstrip("/")).is_file():
                line = _line_of(sources[path], match.start())
                found.append(Problem(path, line, "H001", f"no such file: {target}"))

    # The one vendored module the UI's own code imports by name.
    vendor_module = next(root.glob(f"{VENDOR}/*.js"), None)
    if vendor_module is not None:
        found += check_runtime_names(scripts, sources, vendor_module)
    found += check_wiring(scripts, sources)
    found += check_style_use(styles, sources, [*scripts, *pages])
    found += check_style_defined(styles, sources, [*scripts, *pages])
    found += check_card_widths(scripts, sources)
    # The server half of the page, one directory up from its static files.
    api = root.parent / "api.py"
    if api.is_file():
        found += check_operation_names(scripts, sources, api)

    return sorted(found, key=lambda p: (str(p.path), p.line, p.code))


def vendor_names(vendor_module: Path) -> set[str]:
    """Return the names the vendored module exports, from its bundle."""
    names: set[str] = set()
    for exported in VENDOR_EXPORT.findall(vendor_module.read_text(encoding="utf-8")):
        names.update(name for _, name in VENDOR_NAME.findall(exported))
    return names


def check_runtime_names(
    scripts: list[Path], sources: dict[Path, str], vendor_module: Path
) -> list[Problem]:
    """Report the runtime's names used without their import.

    A module that calls ``useState`` or tags with ``html`` relies on the
    vendored module at run time.  The import that binds them is ordinary
    JavaScript, so a bundler would catch its absence; there is no bundler
    here, and the failure mode is the worst kind of quiet -- the component
    throws mid-render and the page keeps the tab that was open before it.

    Generous by design on both sides.  A name counts as bound if it
    arrives by any route -- a named import from anywhere, a star import,
    or a local ``const``/``function`` of its own -- and as used only in
    the shapes that really reach the runtime: a call, a tagged template,
    or a base class after ``extends``.  A name in a comment or an object
    key is neither, and stays silent.  One report per name, at its first
    use.
    """
    exported = vendor_names(vendor_module)
    found: list[Problem] = []
    for path in scripts:
        text = sources[path]
        bound: set[str] = set()
        for names in IMPORT_NAMES.findall(text):
            bound.update(
                name.strip().split(" as ")[0]
                for name in names.split(",")
                if name.strip()
            )
        # Destructured bindings and parameter names: `[a, b]`, `{k: v}`,
        # `(a, b) =>`.  A parameter shadows the runtime's name harmlessly.
        bound.update(re.findall(r"[([{,]\s*(\w+)\s*[,)\]}=:]", text))
        bound.update(re.findall(r"\b(?:const|let|var|function|class)\s+(\w+)", text))
        bound.update(re.findall(r"\b(\w+)\s+as\s+\w+", text))
        # The code with its strings, templates and comments blanked: a
        # mention in prose or inside a literal never reaches the runtime.
        code = _blank_strings_and_comments(text)
        reported: set[str] = set()
        for pattern in RUNTIME_USE.values():
            for match in pattern.finditer(code):
                name = match.group(1)
                if name not in exported or name in bound or name in reported:
                    continue
                reported.add(name)
                found.append(
                    Problem(
                        path,
                        _line_of(text, match.start()),
                        "J006",
                        f"{name} is used but not imported from {vendor_module.name}",
                    )
                )
    return found


def check_wiring(scripts: list[Path], sources: dict[Path, str]) -> list[Problem]:
    """Check that the modules can actually find each other in a browser."""
    found: list[Problem] = []
    exported = {path: set(EXPORTED.findall(sources[path])) for path in scripts}
    imported: dict[Path, set[str]] = {path: set() for path in scripts}

    for path in scripts:
        text = sources[path]
        for match in IMPORT_ANY.finditer(text):
            target = (path.parent / match.group(1)).resolve()
            if not target.is_file():
                found.append(
                    Problem(
                        path,
                        _line_of(text, match.start()),
                        "J003",
                        f"no such module: {match.group(1)}",
                    )
                )
        for match in IMPORT_NAMED.finditer(text):
            target = (path.parent / match.group(2)).resolve()
            if target not in exported:
                continue  # vendored or missing; reported above if missing
            for raw in match.group(1).split(","):
                name = raw.split(" as ")[0].strip()
                if not name:
                    continue
                imported[target].add(name)
                if name not in exported[target]:
                    found.append(
                        Problem(
                            path,
                            _line_of(text, match.start()),
                            "J004",
                            f"{match.group(2)} does not export {name}",
                        )
                    )
        for match in IMPORT_STAR.finditer(text):
            target = (path.parent / match.group(2)).resolve()
            if target in exported:
                imported[target].update(exported[target])

    for path in scripts:
        if path.name == ENTRY_MODULE:
            continue
        for name in sorted(exported[path] - imported[path]):
            match = re.search(
                rf"^export\s+\S+\s+{re.escape(name)}\b", sources[path], re.M
            )
            line = _line_of(sources[path], match.start()) if match else 1
            found.append(
                Problem(path, line, "J005", f"{name} is exported but never imported")
            )
    return found


def check_style_use(
    styles: list[Path], sources: dict[Path, str], users: list[Path]
) -> list[Problem]:
    """Report CSS classes that the JavaScript and the page never mention.

    Deliberately generous: a class counts as used if its name appears
    anywhere in a module or the page, because half of them are assembled at
    run time (``` `pill ${state}` ```) and a checker that guessed at those
    would cry wolf.  What is left over is a rule for an element that is gone.
    """
    text = "\n".join(sources[path] for path in users)
    found: list[Problem] = []
    for path in styles:
        lines = sources[path].splitlines()
        for name, line in sorted(css_classes(sources[path]).items()):
            if KEEP in lines[line - 1]:
                continue
            if not re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text):
                found.append(Problem(path, line, "C002", f".{name} is used by nothing"))
    return found


# A `class="a b c"` written straight into a template, with nothing
# interpolated into it.  Those are the ones a stylesheet can be held to:
# `class=${`pill ${state}`}` is assembled at run time and is not this
# check's business.
STATIC_CLASS = re.compile(r'class="([^"$<>{}]*)"')


def check_style_defined(
    styles: list[Path], sources: dict[Path, str], users: list[Path]
) -> list[Problem]:
    """Report classes written into markup that no stylesheet defines.

    The mirror of :func:`check_style_use`, and the half that was missing:
    a rule nothing uses is dead weight, but an element wearing a class
    nothing defines is a *bug*, and an invisible one -- the browser applies
    no styling and reports nothing, so the element simply renders as a
    plain block wherever it happens to sit.  That is what
    ``class="modal-backdrop"`` did to the whitelist's "add a tag" dialog:
    a modal that was not a modal, on a page where every other one was.

    Only literal, fully-written class attributes are checked, for the same
    reason the other direction is generous: a name assembled at run time is
    not there to be read.
    """
    defined: set[str] = set()
    for path in styles:
        defined |= set(css_classes(sources[path]))
    found: list[Problem] = []
    for path in users:
        text = sources[path]
        for match in STATIC_CLASS.finditer(text):
            for name in match.group(1).split():
                if name in defined:
                    continue
                found.append(
                    Problem(
                        path,
                        _line_of(text, match.start()),
                        "C003",
                        f".{name} is worn by an element but no stylesheet defines it",
                    )
                )
    return found


# `what="Reading the event log"` or `what=${['A', 'B']}` on a Progress.
# Only the literal forms: a name assembled at run time is not there to be
# read, and is not this check's business.
PROGRESS_WHAT = re.compile(
    r"\$\{Progress\}[^>]*?\bwhat=(\$\{\[[^\]]*\]\}|\"[^\"]*\")", re.S
)
# `ctx.worker.run("Reading the whitelist", ...)` and its f-string cousins.
# An f-string's literal head is what a prefix match can be held to.
WORKER_RUN = re.compile(r"worker\.run\(\s*f?\"([^\"{]*)")
# The other shape: a handler that picks its wording first and passes the
# variable -- `name = "Reading all properties"`, `label = f"Writing {x}"`.
WORKER_RUN_VAR = re.compile(r"worker\.run\(\s*([a-z_][a-z_0-9]*)\s*[,)]")
ASSIGNED = r"^\s*{name}\s*=[^\n]*"
# A whole double-quoted literal, f-string or not, scanned left to right so
# that what sits *between* two of them is never mistaken for a third.
PY_STRING = re.compile(r"f?\"((?:[^\"\\\n]|\\.)*)\"")


def operation_names(api_source: str) -> set[str]:
    """Return the operation names ``web/api.py`` publishes to the link.

    Most are written at the call.  The handlers that choose their wording
    first -- one name for a category and another for the whole charger --
    pass a local instead, so the literals assigned to any local that
    reaches ``worker.run`` count too.
    """
    names = {name for name in WORKER_RUN.findall(api_source) if name}
    for local in set(WORKER_RUN_VAR.findall(api_source)):
        for line in re.findall(
            ASSIGNED.format(name=re.escape(local)), api_source, re.M
        ):
            names.update(
                head
                for literal in PY_STRING.findall(line)
                if (head := literal.split("{")[0])
            )
    return names


def check_operation_names(
    scripts: list[Path], sources: dict[Path, str], api: Path
) -> list[Problem]:
    """Report progress bars waiting on an operation nobody publishes.

    ``Progress`` matches the running operation by prefix, so a panel's
    ``what`` is half of a pair whose other half is a string literal in
    ``web/api.py``.  Neither language's tooling can see the pair: Biome
    does not read Python, pytest does not read the templates, and the
    failure is a bar that never draws -- which is exactly how the
    transactions tab shipped with "Reading *the* charging sessions"
    against a worker saying "Reading charging sessions".

    Both directions of the match are wrong in their own way and both are
    reported.  A ``what`` no operation starts with waits forever; a
    ``what`` shorter than the operation it means matches every other
    read that shares its opening words, which is how the properties
    panel came to draw a bar for the event log.

    One operation may publish under several names -- an f-string's head
    and the fuller wording it grows into, "Reading the event log" and
    "Reading the event log since 7d" -- so what is counted is families,
    not literals: names that all begin with the shortest of them are one
    read under different words, and naming that read is correct.
    """
    published = operation_names(api.read_text(encoding="utf-8"))
    found: list[Problem] = []
    for path in scripts:
        text = sources[path]
        for match in PROGRESS_WHAT.finditer(text):
            line = _line_of(text, match.start())
            for name in re.findall(r"['\"]([^'\"]*)['\"]", match.group(1)):
                matched = sorted(op for op in published if op.startswith(name))
                if not matched:
                    found.append(
                        Problem(
                            path,
                            line,
                            "C004",
                            f"no operation in web/api.py begins {name!r}, "
                            "so this progress bar never draws",
                        )
                    )
                elif not all(op.startswith(matched[0]) for op in matched):
                    found.append(
                        Problem(
                            path,
                            line,
                            "C004",
                            f"{name!r} is a prefix of several unrelated operations "
                            f"({', '.join(matched[:3])}...), so this bar draws for "
                            "other panels' reads",
                        )
                    )
    return found


# `width="full"` on a Card, and the three things that earn it: a table, the
# log, and a plot -- a chart is drawn to the width it is given, and one bar
# per day over a year of charging is a row's worth of content by any reading
# of the word.
CARD_FULL = re.compile(r"\bwidth=\"full\"")
ROW_WIDE = re.compile(r"<table\b|class=\"logs\b|<svg\b")
# Components are top-level functions here, so the one a match sits in runs
# from the `function` line above it to the next one at column zero.
TOP_LEVEL_FUNCTION = re.compile(r"^(?:export\s+)?function\s+\w+", re.M)


def enclosing_function(text: str, index: int) -> str:
    """Return the top-level function body an offset falls inside."""
    starts = [m.start() for m in TOP_LEVEL_FUNCTION.finditer(text)]
    before = [start for start in starts if start <= index]
    if not before:
        return text
    after = [start for start in starts if start > index]
    return text[before[-1] : after[0] if after else len(text)]


def check_card_widths(scripts: list[Path], sources: dict[Path, str]) -> list[Problem]:
    """Report cards claiming a whole row without a row's worth of content.

    ``.card.full`` spans the grid from edge to edge, which also *ends* the
    row -- every card after it starts a new one.  The stylesheet has said
    since the grid was built that this is for content genuinely a row wide
    -- a table, the log, a plot -- and nine cards had it anyway: short
    panels spanning 1600px with the rest of the tab stacked underneath
    them.

    A comment cannot be held to, so this is the same sentence as a check.
    Only the literal ``width="full"`` is read: a card whose width follows
    what it is holding writes ``width=${open ? 'full' : undefined}``, and
    that one is answering the question already.
    """
    found: list[Problem] = []
    for path in scripts:
        text = sources[path]
        for match in CARD_FULL.finditer(text):
            if ROW_WIDE.search(enclosing_function(text, match.start())):
                continue
            found.append(
                Problem(
                    path,
                    _line_of(text, match.start()),
                    "C005",
                    'width="full" ends the row for every card after it, and '
                    'this one holds no table, log or plot -- use "wide" or '
                    "leave it a column",
                )
            )
    return found


def main(argv: list[str] | None = None) -> int:
    """Check the tree named on the command line, or the UI's own."""
    args = list(sys.argv[1:] if argv is None else argv)
    here = Path(__file__).resolve().parent.parent
    root = Path(args[0]) if args else here / "src" / "alfenctl" / "web" / "static"
    problems = check_tree(root)
    for problem in problems:
        print(problem.render(root.parent))
    print(
        f"frontlint: {len(problems)} problem(s) in {root}"
        if problems
        else f"frontlint: clean ({root})"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
