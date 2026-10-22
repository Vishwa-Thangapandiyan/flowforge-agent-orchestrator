"""FLOWFORGE_HOME: per-user state outside the repo (artifacts, connectors.json; vault and logos later)."""

from __future__ import annotations

import os
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parents[2]


def flowforge_home() -> Path:
    return Path(os.getenv("FLOWFORGE_HOME") or Path.home() / ".flowforge")


def database_path(example: bool = False) -> Path:
    """The SQLite file: FLOWFORGE_DB, else example.db in FLOWFORGE_HOME for example data, else flowforge.db next to
    the checkout. The dashboard and the MCP server open the same one (D29)."""
    default = flowforge_home() / "example.db" if example else CHECKOUT / "flowforge.db"
    return Path(os.getenv("FLOWFORGE_DB") or default)
