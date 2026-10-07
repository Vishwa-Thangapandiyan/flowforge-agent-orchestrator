"""Tool health, money and time, meta (D16)."""

import sys
import time

import pytest
from fastapi.testclient import TestClient

from flowforge import main
from flowforge.storage import Storage


def wait_done(client, run_id, timeout_s=30):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "s.db"
    monkeypatch.setenv("FLOWFORGE_DB", str(path))
    return path


def test_savings_add_up_over_finished_runs(db):
    store = Storage(db)
    for run_id, work, makespan, hits, tokens, credits in [("r1", 9000, 4000, 2, 100, 0), ("r2", 3000, 3000, 1, 50, 1.5)]:
        store.start_run(run_id, "w", "W", "critical_path")
        store.finish_run(run_id, "succeeded", {"steps": {}}, {
            "makespan_ms": makespan, "api_calls": 5, "cache_hits": hits, "tokens": tokens,
            "credits": credits, "work_ms": work}, None)
    store.start_run("live", "w", "W", "critical_path")  # still running: not counted
    with TestClient(main.app) as client:
        body = client.get("/stats/savings").json()
    assert body == {"runs": 2, "time_saved_ms": 5000, "calls_skipped": 3, "api_calls": 10,
                    "tokens": 150, "credits": 1.5}


def test_savings_are_zero_with_no_runs(db):
    with TestClient(main.app) as client:
        assert client.get("/stats/savings").json() == {
            "runs": 0, "time_saved_ms": 0, "calls_skipped": 0, "api_calls": 0, "tokens": 0, "credits": 0}


def test_tool_health_states(db, tmp_path, monkeypatch):
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    with TestClient(main.app) as client:
        client.post("/connectors", json={"id": "py", "type": "local", "name": "Python",
                                         "connection": {"command": [sys.executable], "cwd": str(tmp_path)}})
        client.post("/connectors", json={"id": "nokey", "type": "http", "name": "No key", "secret_ref": "env:MISSING_TOKEN",
                                         "connection": {"base_url": "https://api.test"}})
        ok = {"id": "h1", "steps": [{"id": "s", "type": "local", "connector": "py", "params": {"args": ["-c", "print(1)"]}}]}
        wait_done(client, client.post("/runs", json=ok).json()["run_id"])
        health = {h["id"]: h for h in client.get("/health/tools").json()}
        assert health["py"]["status"] == "ok" and health["py"]["last_ok"] and health["py"]["label"].startswith("OK")
        assert health["nokey"]["status"] == "missing_key" and health["nokey"]["label"] == "Key missing"
        assert health["fetch"]["status"] == "idle"

        bad = {"id": "h2", "steps": [{"id": "s", "type": "local", "connector": "py", "retries": 0,
                                      "params": {"args": ["-c", "import sys; sys.exit(3)"]}}]}
        wait_done(client, client.post("/runs", json=bad).json()["run_id"])
        py = next(h for h in client.get("/health/tools").json() if h["id"] == "py")
        assert py["status"] == "failing" and "exit code 3" in py["last_error"]


def test_rate_limit_left_this_minute(db, tmp_path):
    with TestClient(main.app) as client:
        client.post("/connectors", json={"id": "py", "type": "local", "name": "Python", "rate_limit_rpm": 40,
                                         "connection": {"command": [sys.executable], "cwd": str(tmp_path)}})
        wf = {"id": "rl", "steps": [{"id": f"s{i}", "type": "local", "connector": "py",
                                     "params": {"args": ["-c", f"print({i})"]}} for i in range(3)]}
        wait_done(client, client.post("/runs", json=wf).json()["run_id"])
        py = next(h for h in client.get("/health/tools").json() if h["id"] == "py")
        assert py["rate"] == {"rpm": 40, "used_last_minute": 3, "left": 37}


def test_meta(db, monkeypatch):
    with TestClient(main.app) as client:
        assert client.get("/meta").json() == {"project": "My project", "example": False, "version": "0.1.0"}
    monkeypatch.setenv("FLOWFORGE_PROJECT_NAME", "Baby-care shop")
    with TestClient(main.app) as client:
        assert client.get("/meta").json()["project"] == "Baby-care shop"
