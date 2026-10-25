"""SQLite persistence: runs and their events (D16), duration history (D1), persistent cache (D3),
connectors (D10), each map's versions, edits and positions (D17, D21), and a few settings.

Every write of run data, events and cache rows goes through `self.redact` (D16), so the file
never holds a configured key or a known key shape.
"""

from __future__ import annotations

import functools
import json
import sqlite3
import threading
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
CREATE TABLE IF NOT EXISTS flow_versions (
    map_id TEXT NOT NULL DEFAULT 'flow', version INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT,
    decided_at TEXT, fact_sheet_hash TEXT, flow_json TEXT NOT NULL, trace_json TEXT, analysis_json TEXT,
    changes_json TEXT, PRIMARY KEY (map_id, version)
);
CREATE TABLE IF NOT EXISTS flow_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT, json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    map_id TEXT NOT NULL DEFAULT 'flow'
);
CREATE TABLE IF NOT EXISTS flow_positions (
    map_id TEXT NOT NULL DEFAULT 'flow', node_id TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
    PRIMARY KEY (map_id, node_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, dep_id TEXT NOT NULL, kind TEXT NOT NULL,
    status TEXT NOT NULL, latency_ms REAL, summary TEXT NOT NULL, detail_json TEXT, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS checks_by_dep ON checks (dep_id, id);
"""
MAP_IDS = ("deps", "flow")   # the dependency map and the flow map (D21)
FLOW_VERSION_FIELDS = ("version", "status", "created_at", "decided_at", "fact_sheet_hash", "flow_json", "trace_json",
                       "analysis_json", "changes_json")

# Columns added to `runs` after V1; added in place so existing databases keep working (D16).
RUN_COLUMNS = {
    "workflow_name": "TEXT", "started_at": "TEXT", "finished_at": "TEXT", "api_calls": "INTEGER",
    "cache_hits": "INTEGER", "tokens": "INTEGER", "credits": "REAL", "work_ms": "REAL",
    "failure_reason": "TEXT", "steps_json": "TEXT",
}
SUMMARY_FIELDS = ("id", "workflow_id", "workflow_name", "policy", "status", "started_at", "finished_at",
                  "makespan_ms", "api_calls", "cache_hits", "tokens", "credits", "work_ms", "failure_reason",
                  "steps_json")


KEEP_CHECKS = 200   # per dependency (D48)

def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _identity(value: Any) -> Any:
    return value


def _serialised(cls: type) -> type:
    """Every public method holds the storage lock. One sqlite3 connection is shared by the event loop and
    FastAPI's worker threads (sync routes), and a connection must never be used by two threads at once."""
    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def locked(self: Storage, *args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return fn(self, *args, **kwargs)
        return locked

    for name, value in list(vars(cls).items()):
        if callable(value) and not name.startswith("_"):
            setattr(cls, name, wrap(value))
    return cls


@_serialised
class Storage:
    def __init__(self, path: str | Path = "flowforge.db", redact: Callable[[Any], Any] | None = None):
        self._lock = threading.RLock()
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)   # a fresh install has no ~/.flowforge yet (D34)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.redact: Callable[[Any], Any] = redact or _identity
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(runs)")}
        for column, kind in RUN_COLUMNS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {kind}")
        self._migrate_maps()
        self.conn.commit()

    def _migrate_maps(self) -> None:
        """Databases from before D21 held one map: it becomes the flow map. Versions are numbered per map and
        positions are keyed per map, so both tables are rebuilt; edits only gain the column."""
        def has_map_id(table: str) -> bool:
            return "map_id" in {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}

        if not has_map_id("flow_overrides"):
            self.conn.execute("ALTER TABLE flow_overrides ADD COLUMN map_id TEXT NOT NULL DEFAULT 'flow'")
        if not has_map_id("flow_versions"):
            self.conn.executescript("""
                ALTER TABLE flow_versions RENAME TO flow_versions_v1;
                CREATE TABLE flow_versions (map_id TEXT NOT NULL DEFAULT 'flow', version INTEGER NOT NULL,
                    status TEXT NOT NULL, created_at TEXT, decided_at TEXT, fact_sheet_hash TEXT,
                    flow_json TEXT NOT NULL, trace_json TEXT, analysis_json TEXT, changes_json TEXT,
                    PRIMARY KEY (map_id, version));
                INSERT INTO flow_versions SELECT 'flow', version, status, created_at, decided_at, fact_sheet_hash,
                    flow_json, trace_json, analysis_json, changes_json FROM flow_versions_v1;
                DROP TABLE flow_versions_v1;
            """)
        if not has_map_id("flow_positions"):
            self.conn.executescript("""
                ALTER TABLE flow_positions RENAME TO flow_positions_v1;
                CREATE TABLE flow_positions (map_id TEXT NOT NULL DEFAULT 'flow', node_id TEXT NOT NULL,
                    x REAL NOT NULL, y REAL NOT NULL, PRIMARY KEY (map_id, node_id));
                INSERT INTO flow_positions (map_id, node_id, x, y) SELECT 'flow', node_id, x, y FROM flow_positions_v1;
                DROP TABLE flow_positions_v1;
            """)

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

    # --- maps (D17, D21): Planner versions, the user's edits on top, block positions; one set per map ------

    def flows(self, map_id: str) -> FlowStore:
        """The flow-map methods for one map ("deps" or "flow"), so a FlowService never names its map."""
        if map_id not in MAP_IDS:
            raise ValueError(f"unknown map '{map_id}'")
        return FlowStore(self, map_id)

    def add_flow_version(self, map_id: str, status: str, flow: Any, trace: Any, analysis: Any,
                         fact_sheet_hash: str, changes: Any = None) -> int:
        version = 1 + int(self.conn.execute("SELECT COALESCE(MAX(version), 0) FROM flow_versions WHERE map_id = ?",
                                            (map_id,)).fetchone()[0])   # numbered per map, under the lock
        self.conn.execute(
            "INSERT INTO flow_versions (map_id, version, status, created_at, fact_sheet_hash, flow_json, trace_json,"
            " analysis_json, changes_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (map_id, version, status, now_iso(), fact_sheet_hash, self._dump(flow), self._dump(trace),
             self._dump(analysis), self._dump(changes) if changes is not None else None))
        self.conn.commit()
        return version

    def _flow_row(self, row: tuple[Any, ...] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(zip(FLOW_VERSION_FIELDS, row, strict=True))
        for key in ("flow_json", "trace_json", "analysis_json", "changes_json"):
            out[key.removesuffix("_json")] = json.loads(out.pop(key)) if out[key] else None
        return out

    def flow_version(self, map_id: str, version: int) -> dict[str, Any] | None:
        row = self.conn.execute(f"SELECT {', '.join(FLOW_VERSION_FIELDS)} FROM flow_versions"
                                " WHERE map_id = ? AND version = ?", (map_id, version)).fetchone()
        return self._flow_row(row)

    def latest_flow_version(self, map_id: str, status: str = "accepted") -> dict[str, Any] | None:
        row = self.conn.execute(f"SELECT {', '.join(FLOW_VERSION_FIELDS)} FROM flow_versions"
                                " WHERE map_id = ? AND status = ? ORDER BY version DESC LIMIT 1",
                                (map_id, status)).fetchone()
        return self._flow_row(row)

    def flow_versions(self, map_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT version, status, created_at, decided_at, fact_sheet_hash FROM flow_versions"
                                 " WHERE map_id = ? ORDER BY version DESC", (map_id,))
        return [dict(zip(("version", "status", "created_at", "decided_at", "fact_sheet_hash"), r, strict=True))
                for r in rows]

    def count_flow_versions(self, map_id: str) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM flow_versions WHERE map_id = ?", (map_id,)).fetchone()[0])

    def update_flow_version(self, map_id: str, version: int, status: str, flow: Any = None) -> None:
        if flow is None:
            self.conn.execute("UPDATE flow_versions SET status = ?, decided_at = ? WHERE map_id = ? AND version = ?",
                              (status, now_iso(), map_id, version))
        else:
            self.conn.execute("UPDATE flow_versions SET status = ?, decided_at = ?, flow_json = ?"
                              " WHERE map_id = ? AND version = ?",
                              (status, now_iso(), self._dump(flow), map_id, version))
        self.conn.commit()

    def flow_overrides(self, map_id: str) -> list[tuple[int, dict[str, Any]]]:
        rows = self.conn.execute("SELECT id, json FROM flow_overrides WHERE map_id = ? ORDER BY id", (map_id,))
        return [(r[0], json.loads(r[1])) for r in rows]

    def add_flow_override(self, map_id: str, override: Any) -> int:
        cur = self.conn.execute("INSERT INTO flow_overrides (map_id, json) VALUES (?, ?)",
                                (map_id, self._dump(override)))
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_flow_overrides(self, map_id: str, ids: list[int]) -> int:
        if not ids:
            return 0
        cur = self.conn.execute(f"DELETE FROM flow_overrides WHERE map_id = ? AND id IN ({', '.join('?' * len(ids))})",
                                [map_id, *ids])
        self.conn.commit()
        return cur.rowcount

    def flow_positions(self, map_id: str) -> dict[str, tuple[float, float]]:
        return {r[0]: (r[1], r[2]) for r in
                self.conn.execute("SELECT node_id, x, y FROM flow_positions WHERE map_id = ?", (map_id,))}

    def put_flow_positions(self, map_id: str, positions: dict[str, tuple[float, float]], replace: bool = False) -> None:
        if replace:
            self.conn.execute("DELETE FROM flow_positions WHERE map_id = ?", (map_id,))
        self.conn.executemany(
            "INSERT INTO flow_positions (map_id, node_id, x, y) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(map_id, node_id) DO UPDATE SET x = excluded.x, y = excluded.y",
            [(map_id, node_id, float(x), float(y)) for node_id, (x, y) in positions.items()])
        self.conn.commit()

    def clear_map(self, map_id: str) -> None:
        """Forget one map entirely: a different repo starts fresh (D21)."""
        for table in ("flow_versions", "flow_overrides", "flow_positions"):
            self.conn.execute(f"DELETE FROM {table} WHERE map_id = ?", (map_id,))
        self.conn.commit()

    # --- health checks (D24) ----------------------------------------------------------------------

    def add_checks(self, run_id: str, results: list[dict[str, Any]]) -> None:
        """One row per dependency checked. `results` are CheckResult dumps plus `kind`; redacted before storage."""
        at = now_iso()
        rows = []
        for r in results:
            detail = {k: r.get(k) for k in ("reason", "fix", "detail") if r.get(k)}
            rows.append((run_id, r["id"], r["kind"], r["status"], r.get("latency_ms"), self.redact(r["summary"]),
                         json.dumps(self.redact(detail)), at))
        self.conn.executemany("INSERT INTO checks (run_id, dep_id, kind, status, latency_ms, summary, detail_json, at)"
                              " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        for dep_id in {r["id"] for r in results}:   # each dependency keeps its newest KEEP_CHECKS (D48)
            self.conn.execute("DELETE FROM checks WHERE dep_id = ? AND id NOT IN "
                              "(SELECT id FROM checks WHERE dep_id = ? ORDER BY id DESC LIMIT ?)",
                              (dep_id, dep_id, KEEP_CHECKS))
        self.conn.commit()

    def check_history(self, dep_id: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        """Newest first: one dependency's checks, or, without `dep_id`, the latest `limit` of each."""
        if dep_id is not None:
            rows = self.conn.execute("SELECT * FROM checks WHERE dep_id = ? ORDER BY id DESC LIMIT ?",
                                     (dep_id, limit)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY dep_id ORDER BY id DESC) AS n FROM checks)"
                " WHERE n <= ? ORDER BY id DESC", (limit,)).fetchall()
        names = [c[0] for c in self.conn.execute("SELECT * FROM checks LIMIT 0").description]
        out = []
        for row in rows:
            item = dict(zip(names, row[:len(names)], strict=True))
            item.update(json.loads(item.pop("detail_json") or "{}"))
            out.append(item)
        return out

    def latest_latencies(self) -> dict[str, float]:
        """Each dependency's latency from its latest check that measured one (D24), for flow weights (D25)."""
        rows = self.conn.execute(
            "SELECT dep_id, latency_ms FROM checks WHERE id IN (SELECT MAX(id) FROM checks WHERE latency_ms IS NOT NULL"
            " GROUP BY dep_id)").fetchall()
        return {dep: float(ms) for dep, ms in rows}

    def count_checks(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM checks").fetchone()[0]

    def clear_check_history(self) -> None:
        """Settings' "Clear check history" (D40): the results go, the yes to start MCP servers stays."""
        self.conn.execute("DELETE FROM checks")
        self.conn.execute("DELETE FROM settings WHERE key = 'checks_last_run'")
        self.conn.commit()

    def clear_checks(self) -> None:
        """A different repo starts with no check history and no yes to start its MCP servers (D21, D24)."""
        self.conn.execute("DELETE FROM checks")
        self.conn.execute("DELETE FROM settings WHERE key IN ('checks_confirmed', 'checks_last_run')")
        self.conn.commit()

    # --- settings ---------------------------------------------------------------------------------

    def setting(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)"
                          " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        self.conn.commit()


class FlowStore:
    """One map's slice of Storage (D21): the same flow-map methods with the map fixed, so a FlowService never
    names its map. Every call goes through Storage's locked methods."""

    def __init__(self, storage: Storage, map_id: str):
        self.storage = storage
        self.map_id = map_id

    def add_flow_version(self, status: str, flow: Any, trace: Any, analysis: Any, fact_sheet_hash: str,
                         changes: Any = None) -> int:
        return self.storage.add_flow_version(self.map_id, status, flow, trace, analysis, fact_sheet_hash, changes)

    def flow_version(self, version: int) -> dict[str, Any] | None:
        return self.storage.flow_version(self.map_id, version)

    def latest_flow_version(self, status: str = "accepted") -> dict[str, Any] | None:
        return self.storage.latest_flow_version(self.map_id, status)

    def flow_versions(self) -> list[dict[str, Any]]:
        return self.storage.flow_versions(self.map_id)

    def count_flow_versions(self) -> int:
        return self.storage.count_flow_versions(self.map_id)

    def update_flow_version(self, version: int, status: str, flow: Any = None) -> None:
        self.storage.update_flow_version(self.map_id, version, status, flow)

    def flow_overrides(self) -> list[tuple[int, dict[str, Any]]]:
        return self.storage.flow_overrides(self.map_id)

    def add_flow_override(self, override: Any) -> int:
        return self.storage.add_flow_override(self.map_id, override)

    def delete_flow_overrides(self, ids: list[int]) -> int:
        return self.storage.delete_flow_overrides(self.map_id, ids)

    def flow_positions(self) -> dict[str, tuple[float, float]]:
        return self.storage.flow_positions(self.map_id)

    def put_flow_positions(self, positions: dict[str, tuple[float, float]], replace: bool = False) -> None:
        self.storage.put_flow_positions(self.map_id, positions, replace)

    def clear(self) -> None:
        self.storage.clear_map(self.map_id)
