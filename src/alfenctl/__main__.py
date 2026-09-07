"""Allow running the tool with ``python -m alfenctl``."""

from alfenctl.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
