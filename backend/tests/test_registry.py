"""Connector registry, presets, connectors.json and building nodes at start-up (D10)."""

import json
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from flowforge import main
from flowforge.connectors import presets
from flowforge.connectors.models import parse_connector
from flowforge.connectors.registry import ConnectorFileError, Registry, load_connectors_file
from flowforge.nodes.http_node import HTTPNode
from flowforge.nodes.llm_node import LLMNode
from flowforge.nodes.local_node import LocalNode
from flowforge.nodes.mcp_node import MCPNode
from flowforge.storage import Storage

FAKE_GEMINI = "AIzaFAKEFAKEFAKEFAKEFAKE1234"
FAKE_NIM = "nvapi-FAKEFAKEFAKE1234"


def gemini(**over):
    return {"id": "gemini", "type": "llm", "name": "Gemini", "rate_limit_rpm": 15,
            "connection": {"provider": "openai_compatible",
                           "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                           "model": "gemini-3.8-flash"},
            "secret_ref": "env:GEMINI_API_KEY", **over}


# --- registry ----------------------------------------------------------------------------------

def test_save_load_delete_round_trip(tmp_path):
    reg = Registry(Storage(tmp_path / "r.db"))
    reg.save(parse_connector(gemini()))
    assert reg.get("gemini") == parse_connector(gemini()) and [c.id for c in reg.all()] == ["gemini"]
    reg.save(parse_connector(gemini(name="Gemini 2")))
    assert reg.get("gemini").name == "Gemini 2" and len(reg.all()) == 1
    reg.delete("gemini")
    assert reg.get("gemini") is None and reg.all() == []


def test_defaults_seeded_once_and_user_edits_kept(tmp_path):
    reg = Registry(Storage(tmp_path / "r.db"))
    reg.ensure_defaults()
    assert {c.id for c in reg.all()} == {"nim", "fetch"}
    reg.save(reg.get("nim").model_copy(update={"role": "my reasoning model"}))
    reg.ensure_defaults()
    assert len(reg.all()) == 2 and reg.get("nim").role == "my reasoning model"


def test_type_names_are_reserved_as_connector_ids():
    for reserved in ["llm", "mcp", "http", "local", "mock"]:
        with pytest.raises(ValidationError, match="reserved"):
            parse_connector(gemini(id=reserved))


# --- presets -----------------------------------------------------------------------------------

def test_presets_are_valid_and_hold_references_only():
    ids = set(presets.PRESETS)
    assert {"nim", "gemini", "claude", "ollama", "razorpay", "stripe", "fetch"} <= ids
    for c in presets.PRESETS.values():
        assert c.secret_ref is None or c.secret_ref.startswith("env:")
    assert presets.PRESETS["razorpay"].mode == presets.PRESETS["stripe"].mode == "test"
    assert set(presets.CUSTOM) == {"llm", "mcp", "http", "local"}


def test_nim_follows_its_env_settings(monkeypatch):
    monkeypatch.setenv("NIM_RPM", "12")
    monkeypatch.setenv("NIM_DEFAULT_MODEL", "some/model")
    nim = presets.with_env_overrides(presets.PRESETS["nim"])
    assert nim.rate_limit_rpm == 12 and nim.connection.model == "some/model"


# --- connectors.json ---------------------------------------------------------------------------

def test_connectors_file_is_optional(tmp_path):
    assert load_connectors_file(tmp_path / "connectors.json") == []


def test_connectors_file_errors_name_the_file(tmp_path):
    path = tmp_path / "connectors.json"
    path.write_text(json.dumps([gemini(api_key=FAKE_GEMINI)]), encoding="utf-8")
    with pytest.raises(ConnectorFileError, match="connectors.json") as exc:
        load_connectors_file(path)
    assert FAKE_GEMINI not in str(exc.value)  # a mistakenly pasted key is never echoed back
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConnectorFileError, match="connectors.json"):
        load_connectors_file(path)


# --- start-up builds nodes from the registry ---------------------------------------------------

def local_python(tmp_path):
    return {"id": "py", "type": "local", "name": "Python",
            "connection": {"command": [sys.executable], "cwd": str(tmp_path)}}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_GEMINI)
    monkeypatch.setenv("NVIDIA_API_KEY", FAKE_NIM)
    home = os.environ["FLOWFORGE_HOME"]
    with open(os.path.join(home, "connectors.json"), "w", encoding="utf-8") as f:
        json.dump([gemini(), local_python(tmp_path)], f)
    with TestClient(main.app) as client:
        yield client


def test_lifespan_builds_one_node_and_bucket_per_connector(api):
    nodes, buckets = main.state.nodes, main.state.rate_limits
    assert isinstance(nodes["gemini"], LLMNode) and nodes["gemini"].rate_limit_key == "gemini"
    assert buckets["gemini"].rate_per_s == pytest.approx(15 / 60)
    assert isinstance(nodes["nim"], LLMNode) and nodes["llm"] is nodes["nim"]
    assert nodes["nim"].rate_limit_key == "nim" and "nim" in buckets
    assert nodes["llm"].cache_namespace == "llm"  # the default keeps V1 cache keys
    assert isinstance(nodes["fetch"], MCPNode) and isinstance(nodes["mcp"], MCPNode)
    assert isinstance(nodes["py"], LocalNode) and isinstance(nodes["http"], HTTPNode)


def test_list_connectors_shows_refs_never_values(api):
    r = api.get("/connectors")
    assert r.status_code == 200
    by_id = {c["id"]: c for c in r.json()}
    assert {"nim", "fetch", "gemini", "py"} <= by_id.keys()
    assert by_id["gemini"]["secret_ref"] == "env:GEMINI_API_KEY"
    assert FAKE_GEMINI not in r.text and FAKE_NIM not in r.text


def test_no_route_returns_a_secret(api):
    """Walk every GET route without path parameters; no body may contain a configured key."""
    for route in main.app.routes:
        if "GET" in getattr(route, "methods", set()) and "{" not in route.path:
            body = api.get(route.path).text
            assert FAKE_GEMINI not in body and FAKE_NIM not in body, route.path


def test_unknown_connector_rejected_with_422(api):
    wf = {"id": "u", "steps": [{"id": "a", "type": "llm", "connector": "ghost", "params": {"prompt": "x"}}]}
    r = api.post("/runs", json=wf)
    assert r.status_code == 422 and "ghost" in r.json()["detail"]
    wf["steps"][0]["connector"] = "py"  # a local connector on an llm step
    assert api.post("/validate", json=wf).status_code == 422


def test_a_connector_step_runs_end_to_end(api):
    wf = {"id": "e2e", "steps": [{"id": "hello", "type": "local", "connector": "py",
                                  "params": {"args": ["-c", "print('from local')"]}}]}
    run_id = api.post("/runs", json=wf).json()["run_id"]
    for _ in range(100):
        status = api.get(f"/runs/{run_id}").json()
        if status["status"] != "running":
            break
        time.sleep(0.1)
    assert status["status"] == "succeeded"
    step = status["result"]["steps"]["hello"]
    assert step["output"]["stdout"].strip() == "from local" and step["answered_by"] == "py"


def test_bad_connectors_file_stops_start_up(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "bad.db"))
    with open(os.path.join(os.environ["FLOWFORGE_HOME"], "connectors.json"), "w", encoding="utf-8") as f:
        json.dump([gemini(fallback="nowhere")], f)
    with pytest.raises(ConnectorFileError, match="nowhere"), TestClient(main.app):
        pass
