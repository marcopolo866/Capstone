#!/usr/bin/env python3
"""Thin CLI wrapper around desktop_runner.headless_runner.main()."""

# - Keep this file intentionally small so external automation has one stable
#   entrypoint even if the headless implementation moves internally.

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from desktop_runner.headless_runner import main

if __name__ == "__main__":
    raise SystemExit(main())
