"""The Issues page's API and the agent's queue (D37): every issue with its button, Fix through the API, Send to agent,
the agent's `get_fix_requests`, and moving a key in from .env. Fake keys only."""

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from flowforge import main
from flowforge.agent import build_server
from flowforge.security.keystore import KeyStore
from flowforge.storage import Storage

FAKE = "sk_test_FAKEFAKE12345678"
OTHER = "rzp_test_FAKE1234567"
LOCAL = "http://127.0.0.1:8000"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def shop(tmp_path, monkeypatch):
    for k, v in {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "Test",
                 "GIT_COMMITTER_EMAIL": "t@example.test", "GIT_CONFIG_GLOBAL": os.devnull,
                 "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(k, v)
    root = tmp_path / "shop"
    root.mkdir()
    (root / "pay.py").write_text(textwrap.dedent(f"""\
        import httpx

        STRIPE_KEY = "{FAKE}"

        def pay():
            return httpx.post("http://api.stripe.com/v1/charges", headers={{"Authorization": STRIPE_KEY}})
    """))
    (root / ".env").write_text(f"OPENAI_API_KEY={OTHER}\n")
    (root / ".gitignore").write_text(".env\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "flowforge.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(root))
    return root


def issues(c):
    return {i["kind"]: i for i in c.get("/issues").json()["issues"]}


def test_each_issue_says_which_button_it_gets(shop):
    with TestClient(main.app, base_url=LOCAL) as c:
        got = c.get("/issues").json()
    by = {i["kind"]: i for i in got["issues"]}
    assert by["key_in_code"]["action"] == "fix" and by["key_in_code"]["state"] == "open"
    assert by["plain_http"]["action"] == "agent"
    assert got["summary"] == {"high": 1, "medium": 1} and got["example"] is False
    assert FAKE not in json.dumps(got)


def test_preview_then_fix_through_the_api(shop):
    with TestClient(main.app, base_url=LOCAL) as c:
        key = issues(c)["key_in_code"]
        shown = c.post(f"/issues/{key['id']}/preview")
        assert shown.status_code == 200 and FAKE not in shown.text
        assert shown.json()["can_apply"] is True and shown.json()["branch"] == "flowforge/fix-stripe-key"
        done = c.post(f"/issues/{key['id']}/fix")
        assert done.status_code == 200 and FAKE not in done.text
        assert done.json()["branch"] == "flowforge/fix-stripe-key"
        after = issues(c)["key_in_code"]
        assert after["state"] == "fixed" and after["branch"] == "flowforge/fix-stripe-key"   # until you merge it
        assert c.post(f"/issues/{key['id']}/fix").status_code == 409                          # once is enough
    assert KeyStore(shop).env()["STRIPE_KEY"] == FAKE
    assert git(shop, "branch", "--show-current").strip() == "main"


def test_a_fix_that_cant_be_made_says_why(shop):
    (shop / "pay.py").write_text((shop / "pay.py").read_text() + "\n# work in progress\n")
    with TestClient(main.app, base_url=LOCAL) as c:
        key = issues(c)["key_in_code"]
        assert c.post(f"/issues/{key['id']}/preview").json()["can_apply"] is False
        r = c.post(f"/issues/{key['id']}/fix")
        assert r.status_code == 409 and "uncommitted" in r.json()["detail"]
        assert c.post("/issues/no-such-issue/fix").status_code == 404
        plain = issues(c)["plain_http"]
        assert c.post(f"/issues/{plain['id']}/fix").status_code == 409   # an agent's job


def test_fix_and_send_answer_only_to_this_machine(shop):
    with TestClient(main.app, base_url=LOCAL) as c:
        key = issues(c)["key_in_code"]
        for path in (f"/issues/{key['id']}/fix", f"/issues/{key['id']}/send"):
            assert c.post(path, headers={"host": "evil.test"}).status_code == 403


async def test_send_to_agent_queues_it_for_get_fix_requests(shop, tmp_path):
    with TestClient(main.app, base_url=LOCAL) as c:
        plain = issues(c)["plain_http"]
        assert c.post(f"/issues/{plain['id']}/send").json() == {"id": plain["id"], "state": "sent"}
        assert issues(c)["plain_http"]["state"] == "sent"
        assert c.post(f"/issues/{plain['id']}/send").status_code == 200   # sending again changes nothing
    storage = Storage(tmp_path / "flowforge.db")
    async with Client(build_server(shop, storage)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert tools["get_fix_requests"].annotations.read_only_hint is True
        got = json.loads((await client.call_tool("get_fix_requests", {})).content[0].text)
    assert [r["id"] for r in got["requests"]] == [plain["id"]]
    assert "https" in got["requests"][0]["prompt"] and FAKE not in json.dumps(got)


async def test_a_request_leaves_the_queue_once_the_code_no_longer_has_the_issue(shop, tmp_path):
    with TestClient(main.app, base_url=LOCAL) as c:
        c.post(f"/issues/{issues(c)['plain_http']['id']}/send")
    (shop / "pay.py").write_text((shop / "pay.py").read_text().replace("http://", "https://"))
    async with Client(build_server(shop, Storage(tmp_path / "flowforge.db"))) as client:
        got = json.loads((await client.call_tool("get_fix_requests", {})).content[0].text)
    assert got["requests"] == []


def test_move_a_key_in_from_env(shop):
    with TestClient(main.app, base_url=LOCAL) as c:
        r = c.post("/keys/OPENAI_API_KEY/import")
        assert r.status_code == 200 and OTHER not in r.text
        assert c.post("/keys/NOT_IN_ENV/import").status_code == 404
        assert c.post("/keys/OPENAI_API_KEY/import", headers={"host": "evil.test"}).status_code == 403
    assert KeyStore(shop).env() == {"OPENAI_API_KEY": OTHER}


def test_example_mode_saves_keys_and_previews_fixes_but_applies_none(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    with TestClient(main.app, base_url=LOCAL) as c:
        assert c.put("/keys/OLLAMA_API_KEY", json={"value": FAKE}).status_code == 200
        key = issues(c)["key_in_code"]
        assert key["action"] == "fix"
        shown = c.post(f"/issues/{key['id']}/preview").json()
        assert shown["can_apply"] is False and "Example" in shown["why_not"]
        assert c.post(f"/issues/{key['id']}/fix").status_code == 409
        c.delete("/keys/OLLAMA_API_KEY")
