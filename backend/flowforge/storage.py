"""SQLite persistence: runs and their events (D16), duration history (D1), persistent cache (D3),
connectors (D10).

Every write of run data, events and cache rows goes through `self.redact` (D16), so the file
never holds a configured key or a known key shape.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flowforge.scheduler.durations import EWMA_ALPHA, ewma

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
CREATE TABLE IF NOT EXISTS connectors (
    id TEXT PRIMARY KEY, json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS run_events (
    run_id TEXT NOT NULL, seq INTEGER NOT NULL, json TEXT NOT NULL, PRIMARY KEY (run_id, seq)
);
"""

# Columns added to `runs` after V1; added in place so existing databases keep working (D16).
RUN_COLUMNS = {
    "workflow_name": "TEXT", "started_at": "TEXT", "finished_at": "TEXT", "api_calls": "INTEGER",
    "cache_hits": "INTEGER", "tokens": "INTEGER", "credits": "REAL", "work_ms": "REAL",
    "failure_reason": "TEXT", "steps_json": "TEXT",
}
SUMMARY_FIELDS = ("id", "workflow_id", "workflow_name", "policy", "status", "started_at", "finished_at",
                  "makespan_ms", "api_calls", "cache_hits", "tokens", "credits", "work_ms", "failure_reason",
                  "steps_json")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _identity(value: Any) -> Any:
    return value


class Storage:
    def __init__(self, path: str | Path = "flowforge.db", redact: Callable[[Any], Any] | None = None):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.redact: Callable[[Any], Any] = redact or _identity
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(runs)")}
        for column, kind in RUN_COLUMNS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {kind}")
        self.conn.commit()

    def _dump(self, value: Any) -> str:
        return json.dumps(self.redact(value), default=str)

    def save_run(self, run_id: str, result: Any) -> None:
        """`result` is an executor RunResult (V1 API; the app uses start_run/finish_run)."""
        self.conn.execute(
            "INSERT OR REPLACE INTO runs (id, workflow_id, policy, status, makespan_ms, result_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, result.workflow_id, result.policy, result.status, result.makespan_ms,
             self._dump(asdict(result))),
        )
        self.conn.commit()

    # --- run history (D16) ----------------------------------------------------------------------

    def start_run(self, run_id: str, workflow_id: str, workflow_name: str, policy: str,
                  started_at: str | None = None, steps: list[dict[str, Any]] | None = None) -> None:
        """`steps` is the plan outline (id, title, type, connector, depends_on), never params."""
        self.conn.execute(
            "INSERT INTO runs (id, workflow_id, workflow_name, policy, status, started_at, steps_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, workflow_id, self.redact(workflow_name), policy, "running", started_at or now_iso(),
             self._dump(steps or [])),
        )
        self.conn.commit()

    def append_event(self, run_id: str, seq: int, event: dict[str, Any]) -> None:
        self.conn.execute("INSERT OR REPLACE INTO run_events (run_id, seq, json) VALUES (?, ?, ?)",
                          (run_id, seq, self._dump(event)))
        self.conn.commit()

    def finish_run(self, run_id: str, status: str, result: dict[str, Any] | None,
                   totals: dict[str, Any], failure_reason: str | None, finished_at: str | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET status = ?, finished_at = ?, result_json = ?, makespan_ms = ?, api_calls = ?,"
            " cache_hits = ?, tokens = ?, credits = ?, work_ms = ?, failure_reason = ? WHERE id = ?",
            (status, finished_at or now_iso(), self._dump(result) if result is not None else None,
             totals.get("makespan_ms"),
             totals.get("api_calls"), totals.get("cache_hits"), totals.get("tokens"), totals.get("credits"),
             totals.get("work_ms"), self.redact(failure_reason), run_id),
        )
        self.conn.commit()

    def mark_interrupted(self) -> int:
        """Runs still marked running when the server starts were cut off by a stop or crash."""
        cur = self.conn.execute(
            "UPDATE runs SET status = 'interrupted', finished_at = ?, failure_reason = ? WHERE status = 'running'",
            (now_iso(), "The server stopped while this was running."),
        )
        self.conn.commit()
        return cur.rowcount

    def list_runs(self, status: str | None = None, limit: int = 50, before: str | None = None) -> list[dict[str, Any]]:
        sql = f"SELECT {', '.join(SUMMARY_FIELDS)} FROM runs WHERE started_at IS NOT NULL"
        args: list[Any] = []
        if status:
            sql += " AND status = ?"
            args.append(status)
        if before:
            sql += " AND started_at < ?"
            args.append(before)
        sql += " ORDER BY started_at DESC LIMIT ?"
        args.append(limit)
        return [dict(zip(SUMMARY_FIELDS, row, strict=True)) for row in self.conn.execute(sql, args)]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            f"SELECT {', '.join(SUMMARY_FIELDS)}, result_json FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        summary = dict(zip(SUMMARY_FIELDS, row[:-1], strict=True))
        summary["result"] = json.loads(row[-1]) if row[-1] else None
        return summary

    def savings(self) -> dict[str, Any]:
        """Money and time over finished runs: time saved vs one at a time, calls skipped, tokens."""
        row = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(MAX(COALESCE(work_ms, 0) - COALESCE(makespan_ms, 0), 0)), 0),"
            " COALESCE(SUM(cache_hits), 0), COALESCE(SUM(api_calls), 0), COALESCE(SUM(tokens), 0),"
            " COALESCE(SUM(credits), 0) FROM runs WHERE started_at IS NOT NULL AND status != 'running'"
            " AND result_json IS NOT NULL"
        ).fetchone()
        return {"runs": row[0], "time_saved_ms": round(row[1]), "calls_skipped": row[2], "api_calls": row[3],
                "tokens": row[4], "credits": row[5]}

    def recent_results(self, limit: int = 50) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """(summary, result) for the newest finished runs that have a result, newest first."""
        rows = self.conn.execute(
            f"SELECT {', '.join(SUMMARY_FIELDS)}, result_json FROM runs"
            " WHERE result_json IS NOT NULL AND started_at IS NOT NULL ORDER BY started_at DESC LIMIT ?", (limit,))
        return [(dict(zip(SUMMARY_FIELDS, r[:-1], strict=True)), json.loads(r[-1])) for r in rows]

    def run_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT json FROM run_events WHERE run_id = ? ORDER BY seq", (run_id,))
        return [json.loads(r[0]) for r in rows]

    def get_cached(self, key: str) -> tuple[bool, Any]:
        row = self.conn.execute("SELECT output_json FROM cache WHERE key = ?", (key,)).fetchone()
        return (True, json.loads(row[0])) if row else (False, None)

    def put_cached(self, key: str, output: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO cache (key, output_json) VALUES (?, ?)", (key, self._dump(output))
        )
        self.conn.commit()

    def duration_history(self, workflow_id: str) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT step_id, ewma_ms FROM durations WHERE workflow_id = ?", (workflow_id,)
        )
        return dict(rows.fetchall())

    def record_durations(self, workflow_id: str, observed_ms: dict[str, float], alpha: float = EWMA_ALPHA) -> None:
        for step_id, ms in observed_ms.items():
            row = self.conn.execute(
                "SELECT ewma_ms, samples FROM durations WHERE workflow_id = ? AND step_id = ?",
                (workflow_id, step_id),
            ).fetchone()
            prev, n = (None, 0) if row is None else row
            self.conn.execute(
                "INSERT OR REPLACE INTO durations VALUES (?, ?, ?, ?)",
                (workflow_id, step_id, ewma(prev, ms, alpha), n + 1),
            )
        self.conn.commit()

    def connector_rows(self) -> list[tuple[str, str]]:
        """(id, json) for every saved connector, by id. Rows hold secret references, never values."""
        return self.conn.execute("SELECT id, json FROM connectors ORDER BY id").fetchall()

    def put_connector(self, connector_id: str, connector_json: str) -> None:
        self.conn.execute(
            "INSERT INTO connectors (id, json) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET json = excluded.json",
            (connector_id, connector_json),
        )
        self.conn.commit()

    def delete_connector(self, connector_id: str) -> None:
        self.conn.execute("DELETE FROM connectors WHERE id = ?", (connector_id,))
        self.conn.commit()
