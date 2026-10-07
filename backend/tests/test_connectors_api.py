"""Connector CRUD, secret status, logos, test and activity (D16). Keys are references only."""

import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from flowforge import main
from flowforge.scheduler.rate_limit import TokenBucket

FAKE_KEY = "gemini-fake-value-123456"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64


def llm(id="gemini", **over):
    return {"id": id, "type": "llm", "name": "Gemini", "role": "reasoning", "rate_limit_rpm": 15,
            "secret_ref": "env:GEMINI_API_KEY",
            "connection": {"provider": "openai_compatible", "base_url": "https://llm.test/v1", "model": "m"}, **over}


def local(tmp_path, id="py", **over):
    return {"id": id, "type": "local", "name": "Python",
            "connection": {"command": [sys.executable], "cwd": str(tmp_path)}, **over}


def wait_done(client, run_id, timeout_s=30):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "c.db"))
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    with TestClient(main.app) as c:
        yield c


# --- create / read ------------------------------------------------------------------------------

def test_create_then_read_shows_secret_status_never_the_value(client, monkeypatch):
    r = client.post("/connectors", json=llm())
    assert r.status_code == 201
    view = client.get("/connectors/gemini").json()
    assert view["secret"] == {"ref": "env:GEMINI_API_KEY", "status": "set"}
    assert view["managed_by"] == "app" and view["deletable"] is True
    monkeypatch.delenv("GEMINI_API_KEY")
    assert client.get("/connectors/gemini").json()["secret"]["status"] == "missing"
    for text in (r.text, client.get("/connectors").text, client.get("/connectors/gemini").text):
        assert FAKE_KEY not in text


def test_new_connector_gets_a_node_and_its_own_bucket(client):
    client.post("/connectors", json=llm())
    assert main.state.nodes["gemini"].rate_limit_key == "gemini"
    assert isinstance(main.state.rate_limits["gemini"], TokenBucket)


def test_new_connector_is_usable_in_a_run_at_once(client, tmp_path):
    client.post("/connectors", json=local(tmp_path))
    wf = {"id": "now", "steps": [{"id": "s", "type": "local", "connector": "py",
                                  "params": {"args": ["-c", "print('ready')"]}}]}
    body = wait_done(client, client.post("/runs", json=wf).json()["run_id"])
    assert body["status"] == "succeeded" and body["result"]["steps"]["s"]["output"]["stdout"].strip() == "ready"


def test_a_new_key_reference_is_redacted_straight_away(client, tmp_path, monkeypatch):
    monkeypatch.setenv("SCRIPT_TOKEN", "script-token-fake-98765")
    client.post("/connectors", json=local(tmp_path, connection={
        "command": [sys.executable], "cwd": str(tmp_path), "env_refs": {"TOKEN": "env:SCRIPT_TOKEN"}}))
    wf = {"id": "r", "steps": [{"id": "s", "type": "local", "connector": "py",
                                "params": {"args": ["-c", "import os; print(os.environ['TOKEN'])"]}}]}
    body = wait_done(client, client.post("/runs", json=wf).json()["run_id"])
    assert body["result"]["steps"]["s"]["output"]["stdout"].strip() == "[REDACTED]"


def test_invalid_bodies_are_rejected_without_echoing_values(client):
    r = client.post("/connectors", json=llm(api_key="sk_test_FAKEFAKE12345678"))
    assert r.status_code == 422 and "sk_test_FAKE" not in r.text and "api_key" in r.text
    assert client.post("/connectors", json=llm(id="llm")).status_code == 422  # reserved id
    r = client.post("/connectors", json=llm(secret_ref="vault:GEMINI_API_KEY"))
    assert r.status_code == 422 and "Phase 3" in r.text
    assert client.post("/connectors", json=llm(fallback="ghost")).status_code == 422


def test_duplicate_and_unknown(client):
    client.post("/connectors", json=llm())
    assert client.post("/connectors", json=llm()).status_code == 409
    assert client.get("/connectors/ghost").status_code == 404
    assert client.put("/connectors/ghost", json=llm(id="ghost")).status_code == 404
    assert client.delete("/connectors/ghost").status_code == 404


# --- update / delete ------------------------------------------------------------------------------

def test_update_replaces_the_node(client):
    client.post("/connectors", json=llm())
    before = main.state.nodes["gemini"]
    r = client.put("/connectors/gemini", json=llm(name="Gemini Pro", rate_limit_rpm=5))
    assert r.status_code == 200 and r.json()["name"] == "Gemini Pro"
    assert main.state.nodes["gemini"] is not before
    assert main.state.rate_limits["gemini"].rate_per_s == pytest.approx(5 / 60)
    assert client.put("/connectors/gemini", json=llm(id="other")).status_code == 422


def test_defaults_and_fallback_targets_cannot_be_deleted(client):
    assert client.delete("/connectors/nim").status_code == 409
    client.post("/connectors", json=llm())
    client.post("/connectors", json=llm(id="claude", fallback="gemini"))
    assert client.delete("/connectors/gemini").status_code == 409
    assert client.delete("/connectors/claude").status_code == 204
    assert client.delete("/connectors/gemini").status_code == 204
    assert "gemini" not in main.state.nodes


def test_file_managed_connectors_are_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "f.db"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FLOWFORGE_HOME", str(home))
    (home / "connectors.json").write_text(json.dumps([llm()]), encoding="utf-8")
    with TestClient(main.app) as client:
        assert client.get("/connectors/gemini").json()["managed_by"] == "file"
        assert client.put("/connectors/gemini", json=llm(name="x")).status_code == 409
        assert client.delete("/connectors/gemini").status_code == 409
        assert client.post("/connectors/gemini/logo", files={"file": ("a.png", PNG, "image/png")}).status_code == 409


def test_runs_in_flight_keep_their_node(client, tmp_path):
    client.post("/connectors", json=local(tmp_path))
    wf = {"id": "f", "steps": [{"id": "s", "type": "local", "connector": "py",
                                "params": {"args": ["-c", "import time; time.sleep(1); print('done')"]}}]}
    run_id = client.post("/runs", json=wf).json()["run_id"]
    client.delete("/connectors/py")
    assert wait_done(client, run_id)["status"] == "succeeded"


# --- logos ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("data, mime, ext", [(PNG, "image/png", "png"), (JPEG, "image/jpeg", "jpg"),
                                              (WEBP, "image/webp", "webp")])
def test_logo_upload_and_serve(client, data, mime, ext):
    client.post("/connectors", json=llm())
    r = client.post("/connectors/gemini/logo", files={"file": (f"logo.{ext}", data, "application/octet-stream")})
    assert r.status_code == 200 and r.json()["style"]["logo"] == {"type": "upload", "file": f"gemini.{ext}"}
    served = client.get("/connectors/gemini/logo")
    assert served.status_code == 200 and served.content == data
    assert served.headers["content-type"] == mime and served.headers["x-content-type-options"] == "nosniff"


def test_logo_rules(client):
    client.post("/connectors", json=llm())
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert client.post("/connectors/gemini/logo", files={"file": ("a.svg", svg, "image/svg+xml")}).status_code == 415
    assert client.post("/connectors/gemini/logo", files={"file": ("a.png", b"not a png", "image/png")}).status_code == 415
    big = PNG + b"\x00" * (1024 * 1024)
    assert client.post("/connectors/gemini/logo", files={"file": ("a.png", big, "image/png")}).status_code == 413
    assert client.get("/connectors/gemini/logo").status_code == 404  # nothing was saved


# --- test connection, activity, presets -----------------------------------------------------------------

def test_test_connection(client, tmp_path):
    client.post("/connectors", json=local(tmp_path))
    body = client.post("/connectors/py/test").json()
    assert body["ok"] is True
    client.post("/connectors", json=local(tmp_path, id="ghostcmd", connection={
        "command": ["flowforge-no-such-program"], "cwd": str(tmp_path)}))
    body = client.post("/connectors/ghostcmd/test").json()
    assert body["ok"] is False and "not found" in body["message"]
    client.post("/connectors", json=llm())
    r = client.post("/connectors/gemini/test")
    assert r.status_code == 501 and "Phase 3" in r.json()["detail"]


def test_activity_lists_this_connectors_steps(client, tmp_path):
    client.post("/connectors", json=local(tmp_path))
    wf = {"id": "act", "name": "Activity check", "steps": [
        {"id": "hello", "type": "local", "connector": "py", "params": {"args": ["-c", "print(1)"]}},
        {"id": "other", "type": "mock", "params": {"duration_ms": 1}}]}
    run_id = client.post("/runs", json=wf).json()["run_id"]
    wait_done(client, run_id)
    [item] = client.get("/connectors/py/activity").json()
    assert item["run_id"] == run_id and item["step_id"] == "hello" and item["state"] == "succeeded"
    assert item["plan"] == "Activity check" and item["at"] and item["title"] == "hello"


def test_presets_hold_references_only(client):
    presets = {p["preset"]: p for p in client.get("/presets").json()}
    assert {"nim", "gemini", "claude", "ollama", "razorpay", "stripe", "fetch"} <= presets.keys()
    assert {"custom-llm", "custom-mcp", "custom-http", "custom-local"} <= presets.keys()
    assert presets["stripe"]["secret_ref"] == "env:STRIPE_SECRET_KEY"
    assert FAKE_KEY not in json.dumps(presets)
