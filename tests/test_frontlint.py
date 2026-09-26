"""The shared frontend linter, run over this program's own UI.

The checker's own behaviour is tested in `devicectl-core`; what is here is
the run that keeps alfenctl's static tree honest, plus the Biome pass CI
makes alongside it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from devicectl.devtools import frontlint
from devicectl.web import server as webserver

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "alfenctl" / "web" / "static"

# The shared frontend, wherever the installed `devicectl` put it.  Half of
# what this page imports lives there, served under `/core/`, so the checker
# reads both trees at once or it cannot answer a single question about
# either.
CORE = Path(webserver.__file__).resolve().parent / "static"


def test_the_web_ui_passes_its_own_linter() -> None:
    problems = frontlint.check_tree(STATIC, core=CORE)
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
