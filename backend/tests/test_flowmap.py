"""The flow map (D17): Flow JSON, validation and gating, critical path, edits, re-check and the catalog."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from flowforge import main
from flowforge.connectors.models import parse_connector
from flowforge.flowmap import fixture
from flowforge.flowmap.diff import apply_choices, diff
from flowforge.flowmap.models import Flow, Override
from flowforge.flowmap.service import merge
from flowforge.flowmap.validate import FlowError, check, critical

FAKE_KEY = "sk_test_FAKEFAKE12345678"

CONNECTORS = {c.id: c for c in map(parse_connector, [
    {"id": "pay", "type": "http", "name": "Pay", "slot": "payments", "mode": "test",
     "connection": {"base_url": "https://pay.example.test"}},
    {"id": "mail", "type": "mcp", "name": "Mail", "connection": {"command": "npx", "args": ["mail-mcp"]}},
    {"id": "brain", "type": "llm", "name": "Brain",
     "connection": {"provider": "openai_compatible", "base_url": "https://llm.example.test/v1", "model": "m"}},
])}
CODE = [{"type": "code", "ref": "app.py:1"}]


def node(id, kind, **fields):
    return {"id": id, "kind": kind, "title": fields.pop("title", id), "evidence": fields.pop("evidence", CODE), **fields}


def edge(a, b, kind="flow", **fields):
    return {"id": f"{a}__{b}", "source": a, "target": b, "kind": kind, **fields}


def flow(nodes, edges):
    return Flow.model_validate({"nodes": nodes, "edges": edges})


# --- models -------------------------------------------------------------------------------------------

def test_flow_json_rejects_unknown_fields_and_bad_lines():
    with pytest.raises(ValidationError):
        Flow.model_validate({"nodes": [node("a", "start", surprise=1)], "edges": []})
    with pytest.raises(ValidationError, match="unknown block"):
        flow([node("a", "start")], [edge("a", "ghost")])
    with pytest.raises(ValidationError, match="retry"):
        flow([node("a", "code"), node("b", "code")], [edge("a", "b", "retry")])
    with pytest.raises(ValidationError, match="loops back"):
        flow([node("a", "code")], [edge("a", "a")])
    with pytest.raises(ValidationError, match="when"):
        flow([node("d", "decision"), node("b", "end")], [edge("d", "b", "branch")])


def test_fixture_versions_are_valid_maps():
    connectors = {c.id: c for c in map(parse_connector, [
        {"id": i, "type": t, "name": i, "connection": conn} for i, t, conn in [
            ("razorpay", "http", {"base_url": "https://r.example.test"}), ("inventory", "http", {"base_url": "https://i.example.test"}),
            ("higgsfield", "http", {"base_url": "https://h.example.test"}), ("gmail", "mcp", {"command": "x"}),
            ("gemini", "llm", {"provider": "anthropic", "model": "m"}), ("nim", "llm", {"provider": "anthropic", "model": "m"}),
            ("claude", "llm", {"provider": "anthropic", "model": "m"})]])}
    for f in (fixture.flow_v1(), fixture.flow_v2()):
        checked = check(f, connectors)
        assert {n.id for n in checked.nodes if n.kind == "gate"} == {"gate_hold", "gate_send"}  # nothing added by code


# --- validation and gating (D14, D17) -------------------------------------------------------------------

def test_a_loop_is_reported_but_a_retry_is_fine():
    ok = flow([node("a", "start"), node("b", "code")], [edge("a", "b"), edge("b", "b", "retry", max=3)])
    check(ok, CONNECTORS)
    loop = flow([node("a", "code"), node("b", "code")], [edge("a", "b"), edge("b", "a")])
    with pytest.raises(FlowError, match="loop: .*→"):
        check(loop, CONNECTORS)


def test_app_calls_need_a_connected_app_of_the_right_type():
    with pytest.raises(FlowError, match="not connected"):
        check(flow([node("x", "llm", connector="ghost")], []), CONNECTORS)
    with pytest.raises(FlowError, match="mcp app"):
        check(flow([node("x", "llm", connector="mail")], []), CONNECTORS)
    lenient = check(flow([node("x", "llm", connector="ghost")], []), CONNECTORS, strict=False)
    assert lenient.nodes[0].status == "unconfirmed"


def test_no_evidence_means_unconfirmed_and_its_lines_say_so():
    f = check(flow([node("a", "start"), node("x", "llm", connector="brain", evidence=[{"type": "env_name", "ref": ".env:1"}])],
                   [edge("a", "x")]), CONNECTORS)
    assert f.node("x").status == "unconfirmed"
    assert f.edges[0].kind == "unconfirmed"


@pytest.mark.parametrize("call", [
    {"kind": "api", "connector": "pay", "op": {"method": "POST", "path": "/refund"}},
    {"kind": "api", "connector": "pay"},                                   # no method: assume it writes
    {"kind": "mcp", "connector": "mail", "op": {"tool": "send", "read_only": False}},
    {"kind": "mcp", "connector": "mail", "op": {"tool": "send"}},          # not marked read-only
])
def test_code_puts_a_gate_before_every_side_effect(call):
    f = check(flow([node("a", "start"), node("x", call.pop("kind"), **call)], [edge("a", "x")]), CONNECTORS)
    gate = f.node("gate_x")
    assert gate is not None and gate.kind == "gate" and gate.added_by == "policy"
    assert [(e.source, e.target) for e in f.edges] == [("a", "gate_x"), ("gate_x", "x")]


def test_reads_and_llm_calls_are_not_gated():
    f = check(flow([node("a", "start"), node("r", "api", connector="pay", op={"method": "GET"}),
                    node("t", "mcp", connector="mail", op={"tool": "list", "read_only": True}),
                    node("l", "llm", connector="brain")],
                   [edge("a", "r"), edge("r", "t"), edge("t", "l")]), CONNECTORS)
    assert not [n for n in f.nodes if n.kind == "gate"]


def test_a_gate_the_planner_drew_is_kept_and_not_doubled():
    f = check(flow([node("a", "start"), node("g", "gate", evidence=[]), node("x", "api", connector="pay", op={"method": "POST"})],
                   [edge("a", "g"), edge("g", "x")]), CONNECTORS)
    assert [n.id for n in f.nodes if n.kind == "gate"] == ["g"]


def test_unconfirmed_side_effects_get_their_gate_when_confirmed():
    raw = flow([node("a", "start"), node("x", "api", connector="pay", op={"method": "POST"}, evidence=[])], [edge("a", "x")])
    assert not [n for n in check(raw, CONNECTORS).nodes if n.kind == "gate"]
    confirmed, _, _ = merge(raw, [(1, Override(op="confirm", node="x"))])
    assert check(confirmed, CONNECTORS).node("gate_x") is not None


def test_decisions_need_two_labelled_branches():
    one = flow([node("d", "decision"), node("e", "end")], [edge("d", "e", "branch", when="yes")])
    with pytest.raises(FlowError, match="two labelled branches"):
        check(one, CONNECTORS)


def test_critical_path_follows_the_app_not_fallbacks_or_your_steps():
    f = flow([node("s", "start"), node("slow", "llm", connector="brain", estimate_ms=2000),
              node("spare", "llm", connector="brain", estimate_ms=5000), node("fast", "code", estimate_ms=10),
              node("mine", "code", estimate_ms=9000, added_by="user"), node("e", "end")],
             [edge("s", "slow"), edge("slow", "spare", "fallback"), edge("s", "fast"), edge("slow", "e"), edge("fast", "e"),
              edge("s", "mine")])
    cp = critical(check(f, CONNECTORS))
    assert cp.path == ["s", "slow", "e"] and cp.bottleneck == "slow" and cp.length_ms == 2000


# --- edits (overrides) -----------------------------------------------------------------------------------

def test_hiding_a_block_keeps_the_flow_connected():
    f = flow([node("a", "start"), node("b", "code"), node("c", "end")], [edge("a", "b"), edge("b", "c")])
    merged, _, hidden = merge(f, [(7, Override(op="hide", node="b"))])
    assert [n.id for n in merged.nodes] == ["a", "c"] and [(e.source, e.target) for e in merged.edges] == [("a", "c")]
    assert hidden == [{"id": "b", "title": "b", "override": 7}]


def test_edits_on_blocks_that_no_longer_exist_are_skipped():
    f = flow([node("a", "start")], [])
    merged, edits, _ = merge(f, [(1, Override(op="rename", node="gone", title="X"))])
    assert merged == f and edits == {}


# --- diff --------------------------------------------------------------------------------------------------

def test_recheck_diff_groups_new_routes_and_flags_conflicts_with_your_edits():
    overrides = [(1, Override.model_validate(o)) for o in fixture.EXAMPLE_OVERRIDES]
    changes = diff(fixture.flow_v1(), fixture.flow_v2(), overrides, fixture.NOTES_V2)
    kinds = {c["type"]: c for c in changes}
    assert kinds["add"]["nodes"] == ["r_start", "r_mark", "r_end"]
    assert kinds["conflict"]["nodes"] == ["note"] and kinds["conflict"]["choices"]
    assert kinds["remove"]["nodes"] == ["sms"] and kinds["kept"]["nodes"] == ["slack"]
    assert {c["nodes"][0] for c in changes if c["type"] == "change"} == {"score", "high"}


def test_choices_build_the_accepted_version():
    overrides = [(1, Override.model_validate(o)) for o in fixture.EXAMPLE_OVERRIDES]
    v1, v2 = fixture.flow_v1(), fixture.flow_v2()
    changes = diff(v1, v2, overrides, {})
    ids = {c["type"] + ":" + c["nodes"][0]: c["id"] for c in changes}
    take = {ids["add:r_start"]: False, ids["remove:sms"]: False, ids["change:high"]: False, ids["conflict:note"]: "planner"}
    result, drop = apply_choices(v1, v2, changes, take)
    got = {n.id for n in result.nodes}
    assert "r_start" not in got and "sms" in got and result.node("high").title == "Risk ≥ 0.7?"
    assert result.node("score").op.model == "gemini-2.5-flash" and drop == {"note"}
    assert any(e.target == "sms" for e in result.edges)


# --- the API, in example mode -------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    monkeypatch.setenv("INVENTORY_TOKEN", FAKE_KEY)
    with TestClient(main.app) as c:
        yield c


def test_the_example_map(api):
    f = api.get("/flow").json()
    assert f["available"] and f["version"] == 1
    by_id = {n["id"]: n for n in f["nodes"]}
    assert by_id["note"]["connector"] == "ollama" and by_id["note"]["yours"][0]["op"] == "set_connector"
    assert by_id["note"]["planner_connector"] == "claude"
    assert by_id["slack"]["added_by"] == "user" and by_id["sms"]["status"] == "unconfirmed"
    assert by_id["end"]["yours"] == []   # a line from your step doesn't make the Planner's block "yours"
    assert by_id["score"]["tip"]["connector"] == "nim"
    assert f["critical_path"]["path"][-2:] == ["send", "end"] and f["critical_path"]["bottleneck"] == "score"
    assert f["positions"]["score"] == [660, 158]
    planner = api.get("/flow?layer=planner").json()
    assert "slack" not in {n["id"] for n in planner["nodes"]}
    assert {n["id"]: n for n in planner["nodes"]}["note"]["connector"] == "claude"


def test_trace_and_analysis(api):
    trace = api.get("/flow/trace").json()
    assert trace["branches"] == {"risky": "yes", "high": "no"}
    assert {s["node"]: s["outcome"] for s in trace["steps"]}["gate_send"] == "waiting"
    analysis = api.get("/flow/analysis").json()
    assert len(analysis["stages"]) == 6 and analysis["dropped"][0]["title"] == "Send WhatsApp update"


def test_edits_through_the_api(api):
    assert api.post("/flow/overrides", json={"op": "hide", "node": "gate_hold"}).status_code == 422
    r = api.post("/flow/overrides", json={"op": "set_connector", "node": "score", "connector": "gmail"})
    assert r.status_code == 422 and "llm" in r.json()["detail"]
    assert api.post("/flow/overrides", json={"op": "set_connector", "node": "score", "connector": "ghost"}).status_code == 422
    assert api.post("/flow/overrides", json={"op": "rename"}).status_code == 422
    rid = api.post("/flow/overrides", json={"op": "rename", "node": "fetch", "title": "Load the order"}).json()["id"]
    assert {n["id"]: n for n in api.get("/flow").json()["nodes"]}["fetch"]["title"] == "Load the order"
    assert api.delete(f"/flow/overrides/{rid}").status_code == 204
    assert api.delete(f"/flow/overrides/{rid}").status_code == 404
    # confirming the SMS step needs its app connected, and then brings its gate with it (code decides, D14)
    r = api.post("/flow/overrides", json={"op": "confirm", "node": "sms"})
    assert r.status_code == 422 and "not connected" in r.json()["detail"]
    twilio = {"id": "twilio", "type": "http", "name": "Twilio", "connection": {"base_url": "https://sms.example.test"}}
    assert api.post("/connectors", json=twilio).status_code == 201
    assert api.post("/flow/overrides", json={"op": "confirm", "node": "sms"}).status_code == 201
    nodes = {n["id"]: n for n in api.get("/flow").json()["nodes"]}
    assert nodes["sms"]["status"] == "confirmed" and nodes["gate_sms"]["added_by"] == "policy"
    assert api.delete("/flow/nodes/sms/overrides").json() == {"removed": 1}
    # a side-effecting step you add after a non-gate also gets a gate
    new = {"id": "ping", "kind": "mcp", "title": "Ping the team", "connector": "slack", "op": {"tool": "post"}}
    assert api.post("/flow/overrides", json={"op": "add_node", "new_node": new}).status_code == 201
    assert api.post("/flow/overrides", json={"op": "add_edge", "node": "ping", "source": "fetch"}).status_code == 201
    nodes = {n["id"]: n for n in api.get("/flow").json()["nodes"]}
    assert nodes["gate_ping"]["kind"] == "gate"
    # a line that closes a loop is refused
    r = api.post("/flow/overrides", json={"op": "add_edge", "node": "start", "source": "ping"})
    assert r.status_code == 422 and "loop" in r.json()["detail"]


def test_positions(api):
    assert api.put("/flow/positions", json={"positions": {"score": [1, 2]}}).json() == {"saved": 1}
    assert api.get("/flow").json()["positions"]["score"] == [1, 2]
    api.put("/flow/positions", json={"positions": {"fetch": [5, 6]}, "replace": True})
    positions = api.get("/flow").json()["positions"]
    assert positions["fetch"] == [5, 6] and positions["score"] == [660, 158]  # back to the designed layout


def test_recheck_then_accept_keeps_the_old_version(api):
    pending = api.post("/flow/recheck").json()
    assert pending["version"] == 2 and api.get("/flow").json()["pending"] == 2
    by_type = {c["type"]: c for c in pending["changes"]}
    assert set(by_type) == {"add", "change", "conflict", "remove", "kept"}
    assert api.get("/flow/versions/2").json()["changes"] == pending["changes"]
    take = {by_type["conflict"]["id"]: "planner", by_type["add"]["id"]: False}
    after = api.post("/flow/versions/2/accept", json={"take": take}).json()
    nodes = {n["id"]: n for n in after["nodes"]}
    assert after["version"] == 2 and "r_start" not in nodes and "sms" not in nodes
    assert nodes["note"]["connector"] == "claude"   # your Ollama swap dropped, as chosen
    assert [v["version"] for v in api.get("/flow/versions").json()] == [2, 1]
    assert api.post("/flow/versions/2/accept", json={"take": {}}).status_code == 409


def test_discard_and_bad_choices(api):
    v = api.post("/flow/recheck").json()["version"]
    assert api.post(f"/flow/versions/{v}/accept", json={"take": {"c99": True}}).status_code == 409
    assert api.post(f"/flow/versions/{v}/discard").status_code == 204
    assert api.get("/flow").json()["version"] == 1 and api.get("/flow").json()["pending"] is None


def test_catalog_statuses_and_mock_tests(api):
    cat = api.get("/catalog").json()
    status = {i["id"]: i["status"] for i in cat["items"]}
    assert status["gemini"] == "on_map" and status["razorpay"] == "on_map"
    assert status["sirius"] == "connected" and status["slack"] == "connected"   # connected, not in your code
    assert status["twilio"] == "none" and len(cat["items"]) == 56
    assert "inventory" in {o["id"] for o in cat["own"]}
    test = api.post("/catalog/stripe/test").json()
    assert test["mock"] is True and "test mode" in test["steps"][0]["title"]
    assert api.post("/catalog/inventory/test").status_code == 200
    assert api.post("/catalog/nowhere/test").status_code == 404


def test_no_flow_or_catalog_route_returns_a_key(api):
    bodies = [api.get(p).text for p in ("/flow", "/flow?layer=planner", "/flow/trace", "/flow/analysis",
                                        "/flow/versions", "/catalog")]
    bodies.append(json.dumps(api.post("/flow/recheck").json()))
    bodies.append(json.dumps(api.post("/catalog/inventory/test").json()))
    assert all(FAKE_KEY not in b for b in bodies)


def test_without_a_planner_the_map_says_so(tmp_path, monkeypatch):
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "real.db"))
    with TestClient(main.app) as c:
        f = c.get("/flow").json()
        assert f["available"] is False and "Phase 5" in f["message"]
        assert c.post("/flow/recheck").status_code == 409
        assert c.get("/flow/trace").status_code == 404
        assert {i["id"]: i["status"] for i in c.get("/catalog").json()["items"]}["nim"] == "connected"
