"""Run history (D16): runs and redacted events persist, survive restarts, and never hold a key."""

import json
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

from flowforge import main
from flowforge.storage import Storage

LEAKY_VALUE = "leaky-configured-secret-1234"  # matches no key shape: only known via secret_ref
SHAPED_KEY = "sk_test_FAKEFAKE12345678"


def mock(id, ms=5, deps=(), **params):
    return {"id": id, "type": "mock", "depends_on": list(deps), "params": {"duration_ms": ms, "step": id, **params}}


def wait_done(client, run_id, timeout_s=30):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] not in ("running", "queued"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish")


def sse_events(client, run_id):
    events = []
    with client.stream("GET", f"/runs/{run_id}/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
                if events[-1].get("type") == "end":
                    break
    return events


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "history.db"
    monkeypatch.setenv("FLOWFORGE_DB", str(path))
    return path


@pytest.fixture
def client(db_path):
    with TestClient(main.app) as c:
        yield c


# --- lifecycle and listing ---------------------------------------------------------------------

def test_finished_run_is_listed_with_totals(client):
    wf = {"id": "totals", "name": "Nightly check", "steps": [
        mock("a", output={"usage": {"prompt_tokens": 10, "completion_tokens": 5, "credits": 0}}),
        mock("b", deps=["a"]), mock("c", deps=["a"])]}
    run_id = client.post("/runs", json=wf).json()["run_id"]
    wait_done(client, run_id)
    [row] = [r for r in client.get("/runs").json() if r["id"] == run_id]
    assert row["status"] == "succeeded" and row["plan"] == "Nightly check"
    assert row["api_calls"] == 3 and row["cache_hits"] == 0 and row["tokens"] == 15
    assert row["time_ms"] > 0 and row["started_at"] and row["failure_reason"] is None


def test_run_keeps_its_plan_outline_without_params(client):
    run_id = client.post("/runs", json={"id": "outline", "steps": [
        {**mock("fetch", secret_param="sk_test_FAKEFAKE12345678"), "description": "Fetch payments"},
        mock("next", deps=["fetch"])]}).json()["run_id"]
    detail = client.get(f"/runs/{run_id}").json()
    assert detail["steps"] == [
        {"id": "fetch", "title": "Fetch payments", "type": "mock", "connector": None, "depends_on": []},
        {"id": "next", "title": "next", "type": "mock", "connector": None, "depends_on": ["fetch"]}]
    assert "secret_param" not in json.dumps(detail)
    wait_done(client, run_id)
    assert client.get(f"/runs/{run_id}").json()["steps"] == detail["steps"]


def test_summary_lists_the_connectors_a_run_uses(client, tmp_path):
    client.post("/connectors", json={"id": "py", "type": "local", "name": "Python",
                                     "connection": {"command": [sys.executable], "cwd": str(tmp_path)}})
    # the llm step depends on a failing step, so it is skipped and never calls a real model
    wf = {"id": "uses", "steps": [
        mock("gate", fail="permanent"),
        {"id": "think", "type": "llm", "depends_on": ["gate"], "params": {"prompt": "x"}},
        {"id": "script", "type": "local", "connector": "py", "depends_on": ["gate"], "params": {"args": []}}]}
    run_id = client.post("/runs", json=wf).json()["run_id"]
    [row] = [r for r in client.get("/runs").json() if r["id"] == run_id]
    assert row["connectors"] == ["nim", "py"]
    assert wait_done(client, run_id)["status"] == "failed"


def test_events_carry_estimates_and_outputs_for_the_live_view(client):
    wf = {"id": "live", "steps": [
        {**mock("a", ms=5, output={"rows": [1, 2]}), "estimated_ms": 300},
        {**mock("b", ms=5, deps=["a"], output={"usage": {"prompt_tokens": 4, "completion_tokens": 2}}),
         "estimated_ms": 200}]}
    run_id = client.post("/runs", json=wf).json()["run_id"]
    wait_done(client, run_id)
    events = sse_events(client, run_id)
    started = next(e for e in events if e.get("type") == "run" and e["state"] == "started")
    assert started["predicted_critical_path_ms"] == 500 and started["estimates"] == {"a": 300, "b": 200}
    done = {e["step_id"]: e for e in events if e.get("type") == "step" and e["state"] == "succeeded"}
    assert done["a"]["output"] == {"rows": [1, 2]}
    assert done["b"]["output"]["usage"]["prompt_tokens"] == 4


def test_failure_reason_in_plain_words(client):
    wf = {"id": "fails", "steps": [
        {**mock("fetch", fail="permanent"), "description": "Fetch Stripe lifecycle"},
        mock("summarise", deps=["fetch"]), mock("notify", deps=["summarise"]), mock("other")]}
    run_id = client.post("/runs", json=wf).json()["run_id"]
    wait_done(client, run_id)
    [row] = [r for r in client.get("/runs").json() if r["id"] == run_id]
    assert row["status"] == "failed"
    assert row["failure_reason"].startswith('Step "Fetch Stripe lifecycle" failed: simulated permanent failure')
    assert "2 steps after it were skipped" in row["failure_reason"]


def test_status_filter_and_limit(client):
    ok = client.post("/runs", json={"id": "ok", "steps": [mock("a")]}).json()["run_id"]
    bad = client.post("/runs", json={"id": "bad", "steps": [mock("a", fail="permanent")]}).json()["run_id"]
    wait_done(client, ok)
    wait_done(client, bad)
    assert {r["id"] for r in client.get("/runs", params={"status": "failed"}).json()} == {bad}
    assert len(client.get("/runs", params={"limit": 1}).json()) == 1


def test_unknown_run_is_404(client):
    assert client.get("/runs/nope").status_code == 404
    assert client.post("/runs/nope/stop").status_code == 404


# --- persistence across restarts ---------------------------------------------------------------

def test_run_and_events_survive_a_restart(db_path):
    with TestClient(main.app) as first:
        run_id = first.post("/runs", json={"id": "keep", "steps": [mock("a"), mock("b", deps=["a"])]}).json()["run_id"]
        wait_done(first, run_id)
        live_events = sse_events(first, run_id)
        live_result = first.get(f"/runs/{run_id}").json()
    with TestClient(main.app) as second:
        stored = second.get(f"/runs/{run_id}").json()
        assert stored["status"] == "succeeded" and stored["result"] == live_result["result"]
        assert sse_events(second, run_id) == live_events


def test_runs_left_running_become_interrupted(db_path):
    Storage(db_path).start_run("ghost1", "w", "Ghost run", "critical_path")
    with TestClient(main.app) as client:
        [row] = [r for r in client.get("/runs").json() if r["id"] == "ghost1"]
        assert row["status"] == "interrupted"
        assert client.get("/runs/ghost1").json()["status"] == "interrupted"


# --- stop ----------------------------------------------------------------------------------------

def test_stop_cancels_a_running_run(client):
    run_id = client.post("/runs", json={"id": "long", "steps": [mock("slow", ms=30_000)]}).json()["run_id"]
    assert client.post(f"/runs/{run_id}/stop").status_code == 200
    body = wait_done(client, run_id)
    assert body["status"] == "stopped"
    assert [r["status"] for r in client.get("/runs").json() if r["id"] == run_id] == ["stopped"]
    assert client.post(f"/runs/{run_id}/stop").status_code == 409  # already finished


# --- no key anywhere -----------------------------------------------------------------------------

def test_no_secret_in_storage_api_stream_or_logs(tmp_path, db_path, monkeypatch, caplog):
    monkeypatch.setenv("LEAKY_TOKEN", LEAKY_VALUE)
    monkeypatch.setenv("SHAPED_TOKEN", SHAPED_KEY)
    connectors = [{"id": "py", "type": "local", "name": "Python",
                   "connection": {"command": [sys.executable], "cwd": str(tmp_path),
                                  "env_refs": {"LEAKY": "env:LEAKY_TOKEN", "SHAPED": "env:SHAPED_TOKEN"}}}]
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("FLOWFORGE_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "connectors.json").write_text(json.dumps(connectors), encoding="utf-8")
    echo = "import os, sys; print(os.environ['LEAKY'], os.environ['SHAPED'])"
    fail = "import os, sys; sys.stderr.write(os.environ['LEAKY'] + ' ' + os.environ['SHAPED']); sys.exit(2)"
    wf = {"id": "leak", "steps": [
        {"id": "echo", "type": "local", "connector": "py", "params": {"args": ["-c", echo]}},
        {"id": "boom", "type": "local", "connector": "py", "retries": 0, "params": {"args": ["-c", fail]}}]}

    with caplog.at_level("DEBUG"), TestClient(main.app) as client:
        run_id = client.post("/runs", json=wf).json()["run_id"]
        body = wait_done(client, run_id)
        assert body["status"] == "failed"
        assert "[REDACTED]" in body["result"]["steps"]["echo"]["output"]["stdout"]  # the step really printed it
        responses = [client.get(path).text for path in (
            f"/runs/{run_id}", "/runs", "/connectors", "/connectors/py")]
        responses.append(json.dumps(sse_events(client, run_id)))
    with TestClient(main.app) as restarted:  # the stored copy, served after a restart
        responses.append(restarted.get(f"/runs/{run_id}").text)
        responses.append(json.dumps(sse_events(restarted, run_id)))

    surfaces = responses + [caplog.text, db_path.read_bytes().decode("latin-1")]
    for secret in (LEAKY_VALUE, SHAPED_KEY):
        assert not any(secret in s for s in surfaces), secret
    assert os.environ["LEAKY_TOKEN"] == LEAKY_VALUE  # redaction never touches the real environment
