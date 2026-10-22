"""The flow map read from code (D25), through the API: example mode, a chosen repo, a repo without Python."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowforge import main
from flowforge.flow import PYTHON_ONLY
from flowforge.flowmap.models import Flow, FlowEdge, FlowNode
from flowforge.flowmap.validate import check

TRIP_PLANNER = Path(__file__).resolve().parents[2] / "examples" / "trip-planner"


@pytest.fixture
def example(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    with TestClient(main.app) as c:
        yield c


def test_example_mode_draws_the_trip_planner_from_its_code(example):
    f = example.get("/flow?map=flow").json()
    assert f["available"] and f["kind"] == "flow" and f["source"] == "code"
    by_id = {n["id"]: n for n in f["nodes"]}
    assert not any(n["kind"] == "gate" for n in f["nodes"])   # the app's own flow: marked, never gated (D25)
    assert by_id["api-nominatim-1"]["estimate_source"] == "measured" and by_id["api-nominatim-1"]["estimate_ms"] == 420
    assert by_id["llm-ollama-1"]["estimate_source"] == "estimate"
    # writes by D25's rule: the file write is one; a local program and a page read through fetch aren't claimed
    assert {n["id"] for n in f["nodes"] if n["side_effect"]} == {"mcp-files-1"}
    assert f["critical_path"]["path"][0] == "start-plan" and f["critical_path"]["length_ms"] > 0
    assert "mcp-fetch-1" in f["critical_path"]["path"]   # 6.8 s to start: the slowest link
    assert f["written_ms"] > f["critical_path"]["length_ms"]
    assert any(set(a["nodes"]) == {"api-nominatim-2", "api-open-meteo-1", "mcp-fetch-1", "mcp-currency-1"}
               for a in f["advice"])
    assert example.get("/flow").json()["kind"] == "dependencies"   # the default map is still what it depends on


def test_a_re_scan_of_unchanged_code_finds_no_changes(example):
    pending = example.post("/flow/recheck?map=flow").json()
    assert pending["changes"] == []


def test_a_repo_without_python_says_its_flow_waits(tmp_path, monkeypatch):
    repo = tmp_path / "web"
    repo.mkdir()
    (repo / "app.js").write_text("fetch('https://api.weather.test/v1/today');\n")
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "ff.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(repo))
    with TestClient(main.app) as c:
        assert c.get("/flow").json()["available"] is True
        assert c.get("/flow?map=flow").json() == {"available": False, "message": PYTHON_ONLY}


def test_choosing_a_repo_draws_its_flow_too(tmp_path, monkeypatch):
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "ff.db"))
    monkeypatch.delenv("FLOWFORGE_REPO", raising=False)
    with TestClient(main.app) as c:
        assert c.get("/flow?map=flow").json()["available"] is False
        assert c.post("/scan", json={"path": str(TRIP_PLANNER)}).status_code == 201
        f = c.get("/flow?map=flow").json()
        assert f["available"] and f["source"] == "code" and f["counts"]["gates"] == 0


def test_a_code_flow_needs_no_app_and_a_decision_may_have_one_branch():
    flow = Flow(kind="flow", source="code", nodes=[
        FlowNode(id="start-run", kind="start", title="run()", evidence=[{"type": "code", "ref": "main.py:3"}]),
        FlowNode(id="if-1", kind="decision", title="ids?", condition="ids", evidence=[{"type": "code", "ref": "main.py:4"}]),
        FlowNode(id="api-shop-1", kind="api", title="shop", op={"method": "POST"},
                 evidence=[{"type": "code", "ref": "main.py:5"}]),
    ], edges=[FlowEdge(id="a", source="start-run", target="if-1"),
              FlowEdge(id="b", source="if-1", target="api-shop-1", kind="branch", when="yes")])
    checked = check(flow, {})
    assert checked.node("api-shop-1").side_effect is True       # a POST changes something: marked…
    assert not any(n.kind == "gate" for n in checked.nodes)     # …but the app's own code has no approval step
