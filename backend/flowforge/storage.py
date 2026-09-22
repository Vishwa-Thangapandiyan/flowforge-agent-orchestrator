"""SQLite persistence: runs, duration history (D1), persistent cache (D3)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, workflow_id TEXT, policy TEXT, status TEXT,
    makespan_ms REAL, result_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS durations (
    workflow_id TEXT, step_id TEXT, ewma_ms REAL, samples INTEGER,
    PRIMARY KEY (workflow_id, step_id)
);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY, output_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class Storage:
    def __init__(self, path: str | Path = "flowforge.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def get_cached(self, key: str) -> tuple[bool, Any]:
        row = self.conn.execute("SELECT output_json FROM cache WHERE key = ?", (key,)).fetchone()
        return (True, json.loads(row[0])) if row else (False, None)

    def put_cached(self, key: str, output: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO cache (key, output_json) VALUES (?, ?)", (key, json.dumps(output))
        )
        self.conn.commit()

    def duration_history(self, workflow_id: str) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT step_id, ewma_ms FROM durations WHERE workflow_id = ?", (workflow_id,)
        )
        return dict(rows.fetchall())

    def record_durations(self, workflow_id: str, observed_ms: dict[str, float], alpha: float = 0.3) -> None:
        for step_id, ms in observed_ms.items():
            row = self.conn.execute(
                "SELECT ewma_ms, samples FROM durations WHERE workflow_id = ? AND step_id = ?",
                (workflow_id, step_id),
            ).fetchone()
            ewma, n = (ms, 1) if row is None else (alpha * ms + (1 - alpha) * row[0], row[1] + 1)
            self.conn.execute(
                "INSERT OR REPLACE INTO durations VALUES (?, ?, ?, ?)", (workflow_id, step_id, ewma, n)
            )
        self.conn.commit()
