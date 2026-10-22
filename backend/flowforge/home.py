"""FLOWFORGE_HOME: per-user state outside the repo (artifacts, connectors.json; vault and logos later)."""

from __future__ import annotations

import os
from pathlib import Path


def flowforge_home() -> Path:
    return Path(os.getenv("FLOWFORGE_HOME") or Path.home() / ".flowforge")
