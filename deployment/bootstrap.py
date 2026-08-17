#!/usr/bin/env python3
"""Thin, dependency-free entry point invoked by the platform launcher scripts.

Runs with the bare system Python (no venv, no installed package yet), so it
only inserts the program folder onto sys.path and delegates to the real
(stdlib-only) bootstrap logic in agent/app/deployment/bootstrap_core.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.app.deployment.bootstrap_core import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["--project-root", str(PROJECT_ROOT)]))
