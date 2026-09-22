import json

import pytest
from fastapi.testclient import TestClient

from flowforge import main

DIAMOND = {
    "id": "api_diamond",
    "steps": [
        {"id": "a", "type": "mock", "params": {"duration_ms": 5, "step": "a"}},
        {"id": "b", "type": "mock", "depends_on": ["a"], "params": {"duration_ms": 5, "step": "b"}},
        {"id": "c", "type": "mock", "depends_on": ["a"], "params": {"duration_ms": 5, "step": "c"}},
    ],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "api.db"))
    with TestClient(main.app) as c:
        yield c


def test_validate_reports_plan(client):
    body = client.post("/validate", json=DIAMOND).json()
    assert body["order"] == ["a", "b", "c"] and body["levels"] == [["a"], ["b", "c"]]
    assert body["critical_path"] == ["a", "b"]


def test_validate_rejects_cycle_and_schema_errors(client):
    cyclic = {"id": "c", "steps": [{"id": "x", "type": "mock", "depends_on": ["y"]},
                                   {"id": "y", "type": "mock", "depends_on": ["x"]}]}
    r = client.post("/validate", json=cyclic)
    assert r.status_code == 422 and "cycle" in r.json()["detail"]
    assert client.post("/validate", json={"id": "x", "steps": []}).status_code == 422


def test_run_streams_events_then_reports_result(client):
    run_id = client.post("/runs", json=DIAMOND, params={"policy": "critical_path"}).json()["run_id"]
    events = []
    with client.stream("GET", f"/runs/{run_id}/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
                if events[-1].get("type") == "end":
                    break
    step_events = [(e["step_id"], e["state"]) for e in events if e.get("type") == "step"]
    assert ("a", "succeeded") in step_events and ("c", "succeeded") in step_events
    assert events[-2]["type"] == "run" and events[-2]["state"] == "succeeded"

    status = client.get(f"/runs/{run_id}").json()
    assert status["status"] == "succeeded"
    assert status["result"]["steps"]["b"]["state"] == "succeeded"


def test_unknown_run_and_policy(client):
    assert client.get("/runs/nope").status_code == 404
    assert client.post("/runs", json=DIAMOND, params={"policy": "random"}).status_code == 422


def test_example_workflows_served(client):
    names = client.get("/workflows").json()
    assert "stripe_to_razorpay" in names
    assert client.get("/workflows/stripe_to_razorpay").json()["id"] == "stripe_to_razorpay"
    assert client.get("/workflows/..%2Fsecrets").status_code == 404
