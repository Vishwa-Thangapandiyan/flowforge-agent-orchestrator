"""FlowForge as an MCP server (D28, D29), through a real MCP client: in memory, and once over a real stdio pipe."""

import json
import os
import sys
import textwrap
from pathlib import Path

import httpx
from mcp import Client, StdioServerParameters

from flowforge.agent import build_server
from flowforge.api.checks import CONFIRMED_SETTING
from flowforge.api.scan import REPO_SETTING
from flowforge.storage import Storage

ROOT = Path(__file__).resolve().parents[2]
TRIP_PLANNER = ROOT / "examples" / "trip-planner"
FAKE_KEY = "sk_test_FAKEFAKE12345678"
TOOLS = {"get_map", "get_flow", "get_advice", "check_health", "what_changed"}


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    return root


async def call(server, tool: str, args: dict | None = None) -> dict:
    async with Client(server) as client:
        result = await client.call_tool(tool, args or {})
        assert not result.is_error, result.content
        return json.loads(result.content[0].text)


def storage_for(tmp_path: Path, repo: Path | None = None) -> Storage:
    tmp_path.mkdir(parents=True, exist_ok=True)
    storage = Storage(tmp_path / "flowforge.db")
    if repo is not None:
        storage.set_setting(REPO_SETTING, str(repo.resolve()))
    return storage


async def test_an_agent_sees_five_tools_and_only_one_reaches_out(tmp_path):
    server = build_server(TRIP_PLANNER, storage_for(tmp_path))
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == TOOLS
    for name, tool in tools.items():
        assert tool.annotations.read_only_hint is True, name   # no tool writes anything (D29)
        assert tool.description
    assert tools["check_health"].annotations.open_world_hint is True


async def test_get_map_lists_every_dependency_with_where_it_is(tmp_path):
    got = await call(build_server(TRIP_PLANNER, storage_for(tmp_path)), "get_map")
    by_id = {d["id"]: d for d in got["dependencies"]}
    assert {"llm-ollama", "mcp-fetch", "api-nominatim", "api-open-meteo"} <= set(by_id)
    assert any(p.startswith("services/geo.py:") for p in by_id["api-nominatim"]["places"])
    assert by_id["mcp-fetch"]["health"]["status"] == "unchecked"
    assert got["repo"] == "trip-planner"


async def test_get_flow_gives_the_order_and_the_critical_path(tmp_path):
    got = await call(build_server(TRIP_PLANNER, storage_for(tmp_path)), "get_flow")
    calls = {c["id"]: c for c in got["calls"]}
    assert calls["api-nominatim-1"]["ref"] == "planner.py:52" and calls["api-nominatim-1"]["does"] == "find the city"
    assert any(d["question"] == 'Did "find the city" fail?' for d in got["decisions"])
    assert got["critical_path"][0]["id"] == "start-plan" and len(got["critical_path"]) > 2
    assert got["could_be_ms"] < got["as_written_ms"]


async def test_get_advice_hands_over_the_change_and_the_prompt(tmp_path):
    got = await call(build_server(TRIP_PLANNER, storage_for(tmp_path)), "get_advice")
    first = next(a for a in got["advice"] if a["refs"] == ["planner.py:51", "planner.py:52"])
    assert first["change"]["after"][0] == "        home, place = await asyncio.gather("
    assert "Change nothing else" in first["prompt"]


async def test_measured_latencies_and_stored_checks_belong_to_the_dashboards_repo_only(tmp_path):
    storage = storage_for(tmp_path, TRIP_PLANNER)
    storage.add_checks("r1", [{"id": "api-nominatim", "kind": "api", "status": "up", "latency_ms": 420.0,
                               "summary": "Up"}])
    got = await call(build_server(TRIP_PLANNER, storage), "get_flow")
    nominatim = next(c for c in got["calls"] if c["id"] == "api-nominatim-1")
    assert (nominatim["ms"], nominatim["measured"]) == (420.0, True)
    elsewhere = write(tmp_path / "other", {"main.py": "import httpx\n\ndef run():\n    return httpx.get('https://api.nominatim.test/x')\n"})
    got = await call(build_server(elsewhere, storage), "get_map")
    assert all(d["health"]["status"] == "unchecked" for d in got["dependencies"])   # another repo's checks don't count


def health_repo(tmp_path: Path) -> Path:
    return write(tmp_path / "app", {
        "main.py": """
            import httpx

            def run():
                return httpx.get("https://api.weather.test/v1/today")
        """,
        ".mcp.json": json.dumps({"mcpServers": {"notes": {"command": "uvx", "args": ["mcp-notes"]}}}),
    })


async def test_check_health_checks_now_but_starts_only_the_servers_you_said_yes_to(tmp_path):
    repo = health_repo(tmp_path)
    storage = storage_for(tmp_path, repo)
    answered = []

    def answer(request: httpx.Request) -> httpx.Response:
        answered.append(request.url.host)
        return httpx.Response(200, json={})

    server = build_server(repo, storage, transport=httpx.MockTransport(answer))
    got = await call(server, "check_health")
    by_id = {r["id"]: r for r in got["results"]}
    assert by_id["api-api-weather-test"]["status"] == "up" and answered == ["api.weather.test"]
    assert by_id["mcp-notes"]["status"] == "skipped"
    assert "say yes in the dashboard first" in by_id["mcp-notes"]["summary"]
    assert {r["dep_id"] for r in storage.check_history()} == {"api-api-weather-test", "mcp-notes"}   # kept, like Check now
    got = await call(server, "check_health", {"ids": ["api-api-weather-test"]})
    assert [r["id"] for r in got["results"]] == ["api-api-weather-test"]


async def test_a_yes_from_the_dashboard_lets_that_exact_server_start(tmp_path, monkeypatch):
    repo = health_repo(tmp_path)
    storage = storage_for(tmp_path, repo)
    storage.set_setting(CONFIRMED_SETTING, json.dumps(["uvx mcp-notes"]))
    started = []

    async def fake_check(target, root, *, http=None):
        from flowforge.checks.models import CheckResult
        started.append(target.id)
        return CheckResult(id=target.id, status="up", summary="Up: 1 tool")

    monkeypatch.setattr("flowforge.nodes.check_node.check", fake_check)
    got = await call(build_server(repo, storage), "check_health", {"ids": ["mcp-notes"]})
    assert started == ["mcp-notes"] and got["results"][0]["status"] == "up"


async def test_what_changed_compares_the_repo_with_the_map_saved_in_the_dashboard(tmp_path):
    repo = health_repo(tmp_path)
    storage = storage_for(tmp_path, repo)
    saved = {"kind": "dependencies", "nodes": [
        {"id": "app", "kind": "start", "title": "app"},
        {"id": "api-api-weather-test", "kind": "api", "title": "api.weather.test"},
        {"id": "api-api-old-test", "kind": "api", "title": "api.old.test"},
    ], "edges": []}
    storage.add_flow_version("deps", "accepted", saved, None, None, "sha256:x")
    got = await call(build_server(repo, storage), "what_changed")
    assert [d["id"] for d in got["added"]] == ["mcp-notes"]
    assert [d["id"] for d in got["removed"]] == ["api-api-old-test"]
    other = await call(build_server(TRIP_PLANNER, storage_for(tmp_path / "x")), "what_changed")
    assert other["saved"] is False and "dashboard" in other["message"]


async def test_no_answer_ever_carries_a_key(tmp_path):
    repo = write(tmp_path / "leaky", {
        "main.py": f"""
            import asyncio
            import httpx

            API_KEY = "{FAKE_KEY}"

            async def run(token):
                if token == "{FAKE_KEY}":
                    return
                async with httpx.AsyncClient() as client:
                    a = await client.get("https://api.weather.test/v1/today?key={FAKE_KEY}")
                    b = await client.get("https://api.news.test/v2/top", headers={{"Authorization": "Bearer {FAKE_KEY}"}})
                    return a, b
        """,
    })
    storage = storage_for(tmp_path, repo)
    server = build_server(repo, storage, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    async with Client(server) as client:
        for tool in sorted(TOOLS):
            result = await client.call_tool(tool, {})
            text = json.dumps([c.model_dump() for c in result.content])
            assert FAKE_KEY not in text, tool


async def test_each_call_leaves_a_last_call_note_for_the_dashboard(tmp_path):
    storage = storage_for(tmp_path)
    await call(build_server(TRIP_PLANNER, storage), "get_advice")
    note = json.loads(storage.setting("agent_last_call"))
    assert note["tool"] == "get_advice" and note["repo"] == "trip-planner" and note["at"]


async def test_flowforge_mcp_runs_over_a_real_stdio_pipe(tmp_path):
    env = {**os.environ, "FLOWFORGE_DB": str(tmp_path / "flowforge.db"), "FLOWFORGE_HOME": str(tmp_path / "home")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "flowforge.cli", "mcp", "--repo", str(TRIP_PLANNER)],
                                   env=env)
    async with Client(params) as client:
        result = await client.call_tool("get_map", {})
    assert not result.is_error
    assert any(d["id"] == "mcp-fetch" for d in json.loads(result.content[0].text)["dependencies"])


async def test_a_configured_key_value_is_masked_even_in_an_unknown_shape(tmp_path, monkeypatch):
    value = "plainvalue7Qx9Lm2Vb"   # no known key shape: only the configured value gives it away
    monkeypatch.setenv("NVIDIA_API_KEY", value)
    repo = write(tmp_path / "app", {"main.py": f"""
        import httpx

        def run():
            return httpx.get("https://api.weather.test/{value}/today")
    """})
    async with Client(build_server(repo, storage_for(tmp_path))) as client:
        result = await client.call_tool("get_map", {})
    assert value not in result.content[0].text
