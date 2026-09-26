"""The shared template check, run over this program's own UI.

The checker's own behaviour is tested in `devicectl-core`; what is here is
the run that parses every one of alfenctl's `html` templates with the same
code the browser will -- which is the code the shared package ships, since
there is exactly one Preact on the page and it is that one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from devicectl.devtools import htmcheck

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "alfenctl" / "web" / "static"
CORE_STATIC = Path(htmcheck.__file__).resolve().parents[1] / "web" / "static"


def test_the_web_ui_passes_its_own_template_check() -> None:
    if htmcheck.MiniRacer is None:
        pytest.skip("mini-racer is not installed (see CONTRIBUTING.md)")
    problems = htmcheck.check_tree(STATIC, core=CORE_STATIC)
    assert not problems, "\n".join(p.render(ROOT) for p in problems)


def test_the_page_imports_the_one_runtime_there_is() -> None:
    """One Preact on the page, and it is the shared package's.

    A second copy is a second set of hooks: a shared component rendered
    inside a page that loaded its own copy throws on its first `useState`,
    and the page keeps whatever it had drawn before.  So this program
    carries no `vendor/` of its own, and every module reaches the runtime
    through `/core/`.
    """
    assert not list(STATIC.glob("vendor/*"))
    for module in sorted(STATIC.glob("js/*.js")):
        text = module.read_text(encoding="utf-8")
        assert "../vendor/" not in text, module
