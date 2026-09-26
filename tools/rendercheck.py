#!/usr/bin/env python3
"""Draw alfenctl's UI in a real browser and check the layout survives.

The checks themselves are :mod:`devicectl.devtools.rendercheck`, shared with
the other programs built on the same frontend.  What is here is alfenctl's
half: the page comes from the same `tests/webfake.py` charger the web tests
and `tools/screenshot.py` use, so it needs no station, and the tabs are the
nine in `web/static/js/app.js`.

    uv sync --group browser                        # once: playwright
    uv run python -m playwright install chromium   # once: the browser
    uv run tools/rendercheck.py
    uv run tools/rendercheck.py --width 1440 properties
"""

from __future__ import annotations

import os
import sys

from devicectl.devtools import rendercheck

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screenshot import ROOT, TABS, serve_fake


def main(argv: list[str] | None = None) -> int:
    """Run the shared checks over the fake charger."""
    return rendercheck.main(serve_fake, TABS, program="alfenctl", argv=argv)


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
