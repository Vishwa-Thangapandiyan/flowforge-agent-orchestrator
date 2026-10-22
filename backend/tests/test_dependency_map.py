"""The dependency map (D21): a scan drawn through the D17 Planner seam, kept apart from the flow map."""

import json
import sqlite3
from pathlib import Path

import pytest

from flowforge.flowmap.models import Override
from flowforge.flowmap.planner import ScanPlanner
from flowforge.flowmap.service import FlowService, OverrideError
from flowforge.flowmap.validate import check, critical
from flowforge.storage import Storage

TRIP_PLANNER = Path(__file__).resolve().parents[2] / "examples" / "trip-planner"
TRIP_IDS = {"llm-ollama", "api-nominatim", "api-open-meteo", "api-osrm", "api-ip-api-com", "api-google-maps",
            "api-wikipedia", "mcp-time", "mcp-fetch", "mcp-files", "mcp-currency", "local-packing-list"}


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def test_a_scan_becomes_a_dependency_map_without_gates_or_a_critical_path():
    draft = ScanPlanner(TRIP_PLANNER).analyze(0)
    flow = check(draft.flow, {})   # no app is connected, and none needs to be
    assert flow.kind == "dependencies"
    kinds = {n.id: n.kind for n in flow.nodes}
    assert kinds["app"] == "start" and "gate" not in kinds.values()
    assert {n.id for n in flow.nodes if n.kind != "start"} == TRIP_IDS
    lines = {(e.source, e.target) for e in flow.edges}
    assert ("app", "llm-ollama") in lines and ("mcp-fetch", "api-wikipedia") in lines
    assert ("app", "api-wikipedia") not in lines   # reached through the fetch server, not directly
    assert critical(flow).path == []
    ollama = flow.node("llm-ollama")
    assert ollama.catalog == "ollama" and ollama.op.model == "llama3.1:8b" and ollama.connector is None
    assert ollama.evidence[0].type == "code" and ollama.evidence[0].lines
    assert draft.analysis.scan["root"] == "trip-planner"
    assert "AIzaFAKE" not in flow.model_dump_json() + json.dumps(draft.analysis.scan)


def test_servers_only_your_coding_tools_use_hang_off_their_own_start(tmp_path):
    write(tmp_path, {".mcp.json": '{"mcpServers": {"time": {"command": "uvx", "args": ["mcp-server-time"]}}}',
                     "app.py": 'URL = "https://api.weather.test/v1"\n'})
    flow = ScanPlanner(tmp_path).analyze(0).flow
    lines = {(e.source, e.target) for e in flow.edges}
    assert flow.node("tools").kind == "start" and ("tools", "mcp-time") in lines and ("app", "api-api-weather-test") in lines


def test_a_rescan_is_a_new_version_with_a_diff_and_the_old_one_stays(tmp_path):
    repo = write(tmp_path / "repo", {"app.py": 'URL = "https://api.weather.test/v1"\n'})
    storage = Storage(tmp_path / "ff.db")
    service = FlowService(storage.flows("deps"), dict, ScanPlanner(repo))
    assert service.first_map() == 1
    write(repo, {"maps.py": 'TILES = "https://api.tiles.test/v2"\n'})
    pending = service.recheck()
    assert [(c["type"], c["nodes"]) for c in pending["changes"]] == [("add", ["api-api-tiles-test"])]
    current = service.accept(pending["version"], pending["default_take"])
    assert {"api-api-weather-test", "api-api-tiles-test"} <= {n["id"] for n in current["nodes"]}
    assert [v["status"] for v in service.versions()] == ["accepted", "accepted"]


def test_the_two_maps_keep_their_own_versions_edits_and_positions(tmp_path):
    storage = Storage(tmp_path / "ff.db")
    deps, flows = storage.flows("deps"), storage.flows("flow")
    deps.add_flow_version("accepted", {"nodes": []}, None, {"stages": []}, "sha256:a")
    deps.put_flow_positions({"app": (1.0, 2.0)})
    deps.add_flow_override({"op": "hide", "node": "x"})
    assert flows.count_flow_versions() == 0 and flows.flow_positions() == {} and flows.flow_overrides() == []
    flows.put_flow_positions({"app": (9.0, 9.0)})
    assert deps.flow_positions() == {"app": (1.0, 2.0)}
    assert flows.add_flow_version("accepted", {"nodes": []}, None, {"stages": []}, "sha256:b") == 1   # per map


def test_an_old_database_keeps_its_map_as_the_flow_map(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:   # the Phase 3 schema: no map_id anywhere
        conn.executescript("""
            CREATE TABLE flow_versions (version INTEGER PRIMARY KEY, status TEXT NOT NULL, created_at TEXT,
                decided_at TEXT, fact_sheet_hash TEXT, flow_json TEXT NOT NULL, trace_json TEXT, analysis_json TEXT,
                changes_json TEXT);
            CREATE TABLE flow_overrides (id INTEGER PRIMARY KEY AUTOINCREMENT, json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE flow_positions (node_id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL);
            INSERT INTO flow_versions (status, flow_json) VALUES ('accepted', '{"nodes": []}');
            INSERT INTO flow_overrides (json) VALUES ('{"op": "hide", "node": "x"}');
            INSERT INTO flow_positions VALUES ('score', 660, 158);
        """)
    storage = Storage(path)
    old = storage.flows("flow")
    assert old.count_flow_versions() == 1 and len(old.flow_overrides()) == 1
    assert old.flow_positions() == {"score": (660.0, 158.0)}
    assert storage.flows("deps").count_flow_versions() == 0


def test_on_a_dependency_map_you_can_add_a_dependency_without_connecting_it(tmp_path):
    repo = write(tmp_path / "repo", {"app.py": 'URL = "https://api.weather.test/v1"\n'})
    service = FlowService(Storage(tmp_path / "ff.db").flows("deps"), dict, ScanPlanner(repo))
    service.first_map()
    added = service.add_override(Override.model_validate(
        {"op": "add_node", "new_node": {"id": "dep_crm", "kind": "api", "title": "CRM"}}))
    assert added["op"] == "add_node"
    assert "dep_crm" in {n["id"] for n in service.current()["nodes"]}


def test_on_the_flow_map_an_app_call_still_needs_a_connected_app(tmp_path):
    store = Storage(tmp_path / "ff.db").flows("flow")
    start = {"id": "start", "kind": "start", "title": "Webhook", "evidence": [{"type": "code", "ref": "app.py:1"}]}
    store.add_flow_version("accepted", {"nodes": [start]}, None, {"stages": []}, "sha256:a")
    service = FlowService(store, dict, None)
    with pytest.raises(OverrideError, match="isn't connected"):
        service.add_override(Override.model_validate(
            {"op": "add_node", "new_node": {"id": "dep_crm", "kind": "api", "title": "CRM"}}))
