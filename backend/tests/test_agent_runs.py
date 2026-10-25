"""The agent's side of masked keys (D43): get_keys gives masks, run_app asks the running FlowForge to start the app
(waiting for the user's Allow the first time), app_output and stop_app follow it. The agent's MCP server never reads a
value, and no answer ever holds one. Fake keys only."""

import inspect
import json
import sys
import textwrap
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import Client

from flowforge import main
from flowforge.agent import build_server
from flowforge.api import apps as apps_api
from flowforge.security.keystore import KeyStore
from flowforge.storage import Storage

FAKE = "sk_test_FAKEFAKE12345678"
LOCAL, HERE = "http://127.0.0.1:8000", ("127.0.0.1", 50000)
PRINTS_KEY = [sys.executable, "-c", "import os; print('key', os.environ['STRIPE_SECRET_KEY'])"]


@pytest.fixture
def shop(tmp_path, monkeypatch):
    root = tmp_path / "shop"
    root.mkdir()
    (root / "pay.py").write_text(textwrap.dedent("""\
        import os
        STRIPE = os.environ["STRIPE_SECRET_KEY"]
    """))
    KeyStore(root).add("STRIPE_SECRET_KEY", FAKE)
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "flowforge.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(root))
    monkeypatch.setenv("FLOWFORGE_PORT", "8000")
    return root


@pytest.fixture
def no_value_in_the_agents_server(monkeypatch):
    """Every read of a value must come from the dashboard's side, never from agent/server.py."""
    real = KeyStore.env

    def guarded(self):
        for frame in inspect.stack():
            assert not frame.filename.endswith("agent/server.py"), "the agent's MCP server read a value"
        return real(self)

    monkeypatch.setattr(KeyStore, "env", guarded)


def server_for(root, tmp_path):
    return build_server(root, Storage(tmp_path / "agent.db"), dashboard=httpx.ASGITransport(app=main.app,
                                                                                          client=HERE))


async def tool(client, name, args):
    result = await client.call_tool(name, args)
    return result, json.loads(result.content[0].text) if not result.is_error else result.content[0].text


async def test_masks_then_a_run_the_user_allows_then_masked_output(shop, tmp_path, no_value_in_the_agents_server):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        async with Client(server_for(shop, tmp_path)) as agent:
            _, keys = await tool(agent, "get_keys", {})
            [stripe] = [k for k in keys["keys"] if k["name"] == "STRIPE_SECRET_KEY"]
            assert stripe["mask"] == "ffkey://STRIPE_SECRET_KEY" and "run_app" in keys["how"]
            _, waiting = await tool(agent, "run_app", {"command": PRINTS_KEY, "wait_seconds": 1})
            assert waiting["state"] == "waiting" and "Allow" in waiting["message"]
            request = c.get("/p/shop/apps").json()["requests"][0]
            assert request["argv"] == PRINTS_KEY
            c.post(f"/p/shop/apps/requests/{request['id']}/allow")
            _, running = await tool(agent, "run_app", {"command": PRINTS_KEY, "wait_seconds": 1})
            assert running["state"] == "running"
            for _ in range(50):
                _, out = await tool(agent, "app_output", {"run_id": running["run"]["id"]})
                if out["status"] != "running" and out["lines"]:
                    break
                time.sleep(0.1)
            assert out["lines"] == [[1, "key [REDACTED]"]]
            texts = json.dumps([keys, waiting, running, out])
    assert FAKE not in texts


async def test_a_mask_for_a_missing_key_says_to_ask_for_it(shop, tmp_path):
    with TestClient(main.app, base_url=LOCAL, client=HERE):
        async with Client(server_for(shop, tmp_path)) as agent:
            result, text = await tool(agent, "run_app", {"command": ["app", "--k=ffkey://NOT_SAVED"]})
    assert result.is_error and "NOT_SAVED" in text and "request_key" in text


async def test_without_flowforge_running_the_agent_is_told_to_open_it(shop, tmp_path):
    apps_api.server_file().unlink(missing_ok=True)
    async with Client(build_server(shop, Storage(tmp_path / "agent.db"))) as agent:
        result, text = await tool(agent, "run_app", {"command": ["echo", "hi"]})
    assert result.is_error and "Open FlowForge" in text


async def test_stop_app_stops_it(shop, tmp_path, monkeypatch):
    from flowforge import settings

    settings.save({"approve_runs": False})
    with TestClient(main.app, base_url=LOCAL, client=HERE):
        async with Client(server_for(shop, tmp_path)) as agent:
            _, running = await tool(agent, "run_app", {"command": [sys.executable, "-c", "import time; time.sleep(60)"]})
            _, stopped = await tool(agent, "stop_app", {"run_id": running["run"]["id"]})
    assert stopped == {"id": running["run"]["id"], "stopped": True, "repo": "shop"}
