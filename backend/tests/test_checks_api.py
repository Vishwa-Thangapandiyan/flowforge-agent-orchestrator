"""Check now through the API (D24): what will start, the yes it needs, a run through the scheduler, stored verdicts.

The repo below is real and its MCP servers start for real; the one API answers through httpx's MockTransport.
"""

import asyncio
import json
import logging
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from flowforge import main
from flowforge.nodes.check_node import CheckNode

FAKE_KEY = "sk_test_FAKEFAKE12345678"

SERVER = '''
from mcp.server.mcpserver import MCPServer
server = MCPServer("tools")

@server.tool()
def ping() -> str:
    """Answer pong."""
    return "pong"

server.run()
'''

REPO = {
    "app.py": (
        "import subprocess\n"
        "import httpx\n"
        'FORECAST = "https://api.weather.test/v1/forecast"\n'
        'HELP = "https://www.help-pages.test/about"\n'
        "def today():\n"
        "    return httpx.get(FORECAST)\n"
        "def pack():\n"
        '    subprocess.run(["python", "tools/pack.py"], check=True)\n'
    ),
    "tools/pack.py": "print('packed')\n",
    ".mcp.json": json.dumps({"mcpServers": {
        "tools": {"command": "python", "args": ["servers/tools.py"]},
        "broken": {"command": "python", "args": ["servers/broken.py"]},
    }}, indent=2),
    "servers/tools.py": SERVER,
    "servers/broken.py": (
        "import os, sys\n"
        "URL = os.getenv('BROKEN_API_URL')\n"
        f"sys.exit('broken: refused key {FAKE_KEY}')\n"
    ),
}


def make_repo(root):
    for name, text in REPO.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def api(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "shop")
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "ff.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(repo))
    with TestClient(main.app) as c:
        c.calls = []

        def answer(request):
            c.calls.append(str(request.url))
            return httpx.Response(200)
        main.state.nodes["check"] = CheckNode(transport=httpx.MockTransport(answer))
        yield c


def finish(c, run_id, timeout_s=60):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        run = c.get(f"/runs/{run_id}").json()
        if run["status"] != "running" and c.get("/checks").json()["run_id"] == run_id:
            return run
        time.sleep(0.1)
    raise AssertionError("the check run did not finish")


def by_id(c):
    return {i["id"]: i for i in c.get("/checks").json()["items"]}


def test_before_any_check_every_dependency_is_listed_and_unconfirmed_ones_never_will_be(api):
    items = by_id(api)
    assert {i: v["status"] for i, v in items.items()} == {
        "api-api-weather-test": "unchecked", "mcp-tools": "unchecked", "mcp-broken": "unchecked",
        "local-pack": "unchecked", "api-www-help-pages-test": "unconfirmed"}
    assert items["api-www-help-pages-test"]["summary"] == "Not checked: unconfirmed"


def test_starting_mcp_servers_needs_a_yes_first(api):
    plan = api.get("/checks/plan").json()
    assert plan["confirmed"] is False
    assert {(s["name"], s["command"], s["origin"]) for s in plan["starts"]} == {
        ("tools", "python servers/tools.py", "runs a script in this repo"),
        ("broken", "python servers/broken.py", "runs a script in this repo")}
    assert {s["source"] for s in plan["starts"]} == {".mcp.json:3", ".mcp.json:9"}
    refused = api.post("/checks", json={})
    assert refused.status_code == 409 and "start 2 MCP servers" in refused.json()["detail"]


def test_check_now_gives_each_dependency_a_verdict_and_keeps_them(api):
    started = api.post("/checks", json={"confirm": True})
    assert started.status_code == 201
    run = finish(api, started.json()["run_id"])
    assert run["status"] == "succeeded"   # a dependency that is down is a result, not a failed run (D24)
    items = by_id(api)
    assert items["api-api-weather-test"]["status"] == "up" and api.calls == ["https://api.weather.test/v1/forecast"]
    assert items["mcp-tools"]["status"] == "up" and items["mcp-tools"]["summary"] == "Reachable: 1 tool"
    broken = items["mcp-broken"]
    assert broken["status"] == "down" and "broken: refused key" in broken["reason"]
    assert broken["fix"] == "Its code reads BROKEN_API_URL (servers/broken.py:2), but its MCP config gives it no env."
    assert items["local-pack"]["status"] == "up"
    assert items["api-www-help-pages-test"]["status"] == "unconfirmed"
    view = api.get("/checks").json()
    assert view["took_ms"] > 0
    summary = view["summary"]
    assert summary == {"up": 3, "warn": 0, "down": 1, "skipped": 0, "unchecked": 0, "unconfirmed": 1}

    # the yes is kept for these commands; one dependency can be checked alone; history grows
    again = api.post("/checks", json={"ids": ["mcp-broken"]})
    assert again.status_code == 201
    finish(api, again.json()["run_id"])
    history = api.get("/checks/mcp-broken").json()
    assert [h["status"] for h in history] == ["down", "down"]
    assert by_id(api)["mcp-broken"]["history"] == ["down", "down"]


def test_a_hidden_dependency_is_not_checked(api):
    api.post("/flow/overrides", json={"op": "hide", "node": "mcp-broken"})
    plan = api.get("/checks/plan").json()
    assert {s["name"] for s in plan["starts"]} == {"tools"}
    assert "mcp-broken" not in by_id(api)


def test_no_key_value_reaches_storage_responses_or_logs(api, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    run_id = api.post("/checks", json={"confirm": True}).json()["run_id"]
    finish(api, run_id)
    bodies = [api.get(p).text for p in ("/checks", "/checks/plan", "/checks/mcp-broken", f"/runs/{run_id}")]
    assert all(FAKE_KEY not in b for b in bodies)
    assert FAKE_KEY not in caplog.text
    assert FAKE_KEY.encode() not in (tmp_path / "ff.db").read_bytes()


def test_an_unknown_dependency_has_no_history(api):
    assert api.get("/checks/api-nowhere").status_code == 404


def test_a_yes_covers_only_the_servers_you_were_shown(api):
    """Check this one on an MCP server confirms that server, not every other one (D24)."""
    one = api.post("/checks", json={"ids": ["mcp-tools"], "confirm": True})
    assert one.status_code == 201
    finish(api, one.json()["run_id"])
    assert api.get("/checks/plan").json()["confirmed"] is False
    refused = api.post("/checks", json={})
    assert refused.status_code == 409 and "start 1 MCP server " in refused.json()["detail"]


def test_a_dependency_you_added_is_checked_at_its_address_and_a_placeholder_is_not(api):
    for node in ({"id": "dep_remote", "kind": "mcp", "title": "Remote tools", "what": "https://mcp.tools.test/mcp?token=x"},
                 {"id": "dep_new", "kind": "api", "title": "New dependency", "what": "A dependency you added."}):
        api.post("/flow/overrides", json={"op": "add_node", "new_node": node})
    run_id = api.post("/checks", json={"ids": ["dep_remote", "dep_new"]}).json()["run_id"]
    finish(api, run_id)
    items = by_id(api)
    assert items["dep_remote"]["status"] == "up" and "https://mcp.tools.test/mcp" in api.calls   # no query sent
    assert items["dep_new"]["status"] == "skipped"
    assert items["dep_new"]["summary"] == "Not checked: no address in the code"


def test_a_check_that_breaks_is_not_counted_as_the_dependency_being_down(api):
    class Broken(CheckNode):
        async def run(self, params):
            raise RuntimeError("a bug in the check")
    main.state.nodes["check"] = Broken()
    finish(api, api.post("/checks", json={"ids": ["local-pack"]}).json()["run_id"])
    item = by_id(api)["local-pack"]
    assert item["status"] == "skipped" and item["summary"] == "The check couldn't run"


def test_steps_that_never_ran_record_nothing(api):
    class Slow(CheckNode):
        async def run(self, params):
            await asyncio.sleep(30)
    main.state.nodes["check"] = Slow()
    run_id = api.post("/checks", json={"ids": ["local-pack"]}).json()["run_id"]
    time.sleep(0.3)
    api.post(f"/runs/{run_id}/stop")
    deadline = time.monotonic() + 10
    while api.get(f"/runs/{run_id}").json()["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.1)
    time.sleep(0.3)
    assert api.get("/checks/local-pack").json() == []
    assert by_id(api)["local-pack"]["status"] == "unchecked"


def test_queued_mcp_checks_get_time_to_wait_their_turn():
    """Only 3 MCP servers start at once (D24); a step's timeout covers its wait in that queue."""
    from flowforge.api.checks import check_workflow
    from flowforge.checks import CheckTarget, probes
    targets = [CheckTarget(id=f"mcp-{i}", kind="mcp", name=str(i), command=["python", f"s{i}.py"]) for i in range(7)]
    workflow = check_workflow(targets + [CheckTarget(id="api-x", kind="api", name="x", target="https://x.test")], "/repo")
    timeouts = {s.params["target"]["id"]: s.timeout_s for s in workflow.steps}
    assert timeouts["mcp-0"] >= 3 * probes.MCP_TIMEOUT_S   # 7 servers, 3 at a time: up to 3 rounds
    assert timeouts["api-x"] < probes.MCP_TIMEOUT_S
