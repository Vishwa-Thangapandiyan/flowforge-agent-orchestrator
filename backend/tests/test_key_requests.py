"""Keys your agent asks for (D38): `request_key` puts the request on the Keys page, `wait_for_keys` returns as soon as
the user pastes it. No tool takes, reads or returns a value. Fake keys only."""

import asyncio
import json
import textwrap

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from flowforge import main
from flowforge.agent import build_server
from flowforge.api.scan import REPO_SETTING
from flowforge.security.keystore import KeyStore
from flowforge.storage import Storage

FAKE = "sk_test_FAKEFAKE12345678"
LOCAL, HERE = "http://127.0.0.1:8000", ("127.0.0.1", 50000)


@pytest.fixture
def shop(tmp_path, monkeypatch):
    root = tmp_path / "shop"
    root.mkdir()
    (root / "pay.py").write_text(textwrap.dedent("""\
        import httpx

        def pay():
            return httpx.post("https://api.stripe.com/v1/charges")
    """))
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "flowforge.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(root))
    return root


def storage_for(tmp_path, root) -> Storage:
    storage = Storage(tmp_path / "flowforge.db")
    storage.set_setting(REPO_SETTING, str(root.resolve()))   # the dashboard maps this repo
    return storage


async def call(server, tool, args):
    async with Client(server) as client:
        result = await client.call_tool(tool, args)
        return result, json.loads(result.content[0].text)


async def test_a_request_shows_on_the_keys_page_first(shop, tmp_path):
    server = build_server(shop, storage_for(tmp_path, shop))
    _, got = await call(server, "request_key", {"name": "STRIPE_SECRET_KEY", "why": "for Stripe in pay.py"})
    assert got["status"] == "requested" and "Keys page" in got["message"]
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        keys = c.get("/keys").json()
    assert [r["name"] for r in keys["requests"]] == ["STRIPE_SECRET_KEY"]
    assert keys["requests"][0]["why"] == "for Stripe in pay.py"
    row = next(k for k in keys["keys"] if k["name"] == "STRIPE_SECRET_KEY")
    assert row["status"] == "missing" and row["requested"] is True and row["deps"] == ["api-stripe"]


async def test_a_request_clears_once_the_key_is_saved(shop, tmp_path):
    server = build_server(shop, storage_for(tmp_path, shop))
    await call(server, "request_key", {"name": "STRIPE_SECRET_KEY", "why": "for Stripe"})
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        c.put("/keys/STRIPE_SECRET_KEY", json={"value": FAKE})
        keys = c.get("/keys").json()
    assert keys["requests"] == []
    assert next(k for k in keys["keys"] if k["name"] == "STRIPE_SECRET_KEY")["status"] == "saved"


async def test_wait_for_keys_returns_the_moment_the_key_is_saved(shop, tmp_path):
    server = build_server(shop, storage_for(tmp_path, shop))

    async def paste_soon():
        await asyncio.sleep(1.2)
        KeyStore(shop).add("STRIPE_SECRET_KEY", FAKE)

    paster = asyncio.create_task(paste_soon())
    result, got = await call(server, "wait_for_keys", {"names": ["STRIPE_SECRET_KEY"], "seconds": 20})
    await paster
    assert (got["saved"], got["waiting"], got["done"]) == (["STRIPE_SECRET_KEY"], [], True)
    assert FAKE not in result.content[0].text


async def test_wait_for_keys_stops_when_the_time_is_up(shop, tmp_path):
    server = build_server(shop, storage_for(tmp_path, shop))
    _, got = await call(server, "wait_for_keys", {"names": ["STRIPE_SECRET_KEY"], "seconds": 1})
    assert got["done"] is False and got["waiting"] == ["STRIPE_SECRET_KEY"] and "again" in got["message"]


async def test_names_are_checked_and_no_value_is_ever_taken(shop, tmp_path):
    server = build_server(shop, storage_for(tmp_path, shop))
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        for name in ("request_key", "wait_for_keys"):
            assert "value" not in json.dumps(tools[name].input_schema)
        bad = await client.call_tool("request_key", {"name": "not a name", "why": "x"})
        assert bad.is_error and "env var name" in bad.content[0].text   # the agent reads why


async def test_the_agents_server_still_never_reads_a_value(shop, tmp_path, monkeypatch):
    KeyStore(shop).add("STRIPE_SECRET_KEY", FAKE)

    def refuse(self):
        raise AssertionError("the MCP server read a key's value")

    monkeypatch.setattr(KeyStore, "env", refuse)
    server = build_server(shop, storage_for(tmp_path, shop))
    _, got = await call(server, "wait_for_keys", {"names": ["STRIPE_SECRET_KEY"], "seconds": 1})
    assert got["saved"] == ["STRIPE_SECRET_KEY"]


async def test_a_request_belongs_to_its_folder(shop, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    server = build_server(other, storage_for(tmp_path, other))
    await call(server, "request_key", {"name": "STRIPE_SECRET_KEY", "why": "for another app"})
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:   # the dashboard maps `shop`
        c.post("/scan", json={"path": str(shop), "replace": True})
        assert c.get("/keys").json()["requests"] == []
