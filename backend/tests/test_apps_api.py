"""The agent's app runs through the dashboard (D43): a new command waits for your Allow, then runs with the keys filled
in; the same command later runs at once; output is masked; nothing answers with a value. Fake keys only."""

import json
import os
import stat
import sys
import textwrap
import time

import pytest
from fastapi.testclient import TestClient

from flowforge import main, settings
from flowforge.api import apps as apps_api
from flowforge.security.keystore import KeyStore

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
    return root


def client():
    return TestClient(main.app, base_url=LOCAL, client=HERE)


def agent(c, path, body=None):
    headers = {"X-FlowForge-Token": apps_api.token()}
    return c.post(path, json=body, headers=headers) if body is not None else c.get(path, headers=headers)


def until_output(c, run_id, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        got = c.get(f"/p/shop/apps/runs/{run_id}/output").json()
        if got["status"] != "running" and got["lines"]:
            return got
        time.sleep(0.1)
    raise AssertionError("no output")


def test_a_new_command_waits_for_your_allow_then_runs_masked(shop):
    with client() as c:
        asked = agent(c, "/p/shop/apps/run", {"argv": PRINTS_KEY})
        assert asked.status_code == 202 and asked.json()["state"] == "waiting"
        request = asked.json()["request"]
        assert request["keys"] == ["STRIPE_SECRET_KEY"] and request["argv"] == PRINTS_KEY
        assert c.get("/p/shop/apps").json()["requests"][0]["id"] == request["id"]   # the prompt card
        assert c.post(f"/p/shop/apps/requests/{request['id']}/allow").json()["state"] == "allowed"
        decided = agent(c, f"/p/shop/apps/requests/{request['id']}").json()
        assert decided["state"] == "allowed"
        out = until_output(c, decided["run"]["id"])
        assert out["lines"] == [[1, "key [REDACTED]"]]
        again = agent(c, "/p/shop/apps/run", {"argv": PRINTS_KEY})   # the same command: no question this time
        assert again.status_code == 201 and again.json()["state"] == "running"
        texts = [r.text for r in (asked, again)] + [json.dumps(out), c.get("/p/shop/apps").text]
    assert all(FAKE not in t for t in texts)


def test_deny_starts_nothing(shop):
    with client() as c:
        request = agent(c, "/p/shop/apps/run", {"argv": PRINTS_KEY}).json()["request"]
        assert c.post(f"/p/shop/apps/requests/{request['id']}/deny").json()["state"] == "denied"
        assert agent(c, f"/p/shop/apps/requests/{request['id']}").json()["state"] == "denied"
        assert c.get("/p/shop/apps").json() == {"requests": [], "runs": [], "approve_runs": True}


def test_a_mask_for_a_key_that_isnt_saved_is_refused_before_asking(shop):
    with client() as c:
        r = agent(c, "/p/shop/apps/run", {"argv": ["app", "--k=ffkey://NOT_SAVED"]})
        assert r.status_code == 409 and "NOT_SAVED" in r.json()["detail"]
        assert c.get("/p/shop/apps").json()["requests"] == []


def test_with_approval_off_a_command_runs_at_once(shop):
    settings.save({"approve_runs": False})
    with client() as c:
        r = agent(c, "/p/shop/apps/run", {"argv": PRINTS_KEY})
        assert r.status_code == 201 and r.json()["state"] == "running"


@pytest.mark.parametrize("headers", [{}, {"X-FlowForge-Token": "wrong"}])
def test_only_flowforges_own_mcp_server_can_ask(shop, headers):
    with client() as c:
        assert c.post("/p/shop/apps/run", json={"argv": PRINTS_KEY}, headers=headers).status_code == 403


def test_allow_deny_and_stop_answer_only_to_the_dashboard_on_this_machine(shop):
    with client() as c:
        request = agent(c, "/p/shop/apps/run", {"argv": PRINTS_KEY}).json()["request"]
        evil = {"host": "evil.test"}
        assert c.post(f"/p/shop/apps/requests/{request['id']}/allow", headers=evil).status_code == 403
        assert c.post("/p/shop/apps/runs/nope/stop", headers=evil).status_code == 403


def test_stop_ends_a_run(shop):
    settings.save({"approve_runs": False})
    with client() as c:
        run = agent(c, "/p/shop/apps/run", {"argv": [sys.executable, "-c", "import time; time.sleep(60)"]}).json()
        assert c.post(f"/p/shop/apps/runs/{run['run']['id']}/stop").json() == {"id": run["run"]["id"],
                                                                                "stopped": True}


def test_the_server_file_tells_the_agent_where_flowforge_is_and_only_you_can_read_it(shop, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_PORT", "8765")
    with client():
        found = apps_api.read_server_file()
        assert found["port"] == 8765 and found["token"] == apps_api.token()
        path = apps_api.server_file()
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.exists()   # gone when FlowForge stops


def test_started_by_plain_uvicorn_the_first_request_tells_the_agent_where_flowforge_is(shop, monkeypatch):
    """Codex review: `uvicorn flowforge.main:app` sets no FLOWFORGE_PORT; the first request's own address is used."""
    monkeypatch.delenv("FLOWFORGE_PORT", raising=False)
    with client() as c:
        assert apps_api.read_server_file() is None
        c.get("/meta")
        found = apps_api.read_server_file()
        assert found["port"] == 8000 and found["token"] == apps_api.token()


def test_one_command_gives_one_card_and_at_most_one_run_even_at_the_same_moment(shop, monkeypatch):
    """Codex review: two asks for the same command at once make one request; two Allows at once start one run."""
    from concurrent.futures import ThreadPoolExecutor

    real_start = apps_api._start

    def slow_start(s, argv):   # widen the window two Allows could race through
        time.sleep(0.2)
        return real_start(s, argv)

    monkeypatch.setattr(apps_api, "_start", slow_start)
    with client() as c:
        with ThreadPoolExecutor(4) as pool:
            asks = list(pool.map(lambda _: agent(c, "/p/shop/apps/run", {"argv": PRINTS_KEY}).json(), range(4)))
        assert len({a["request"]["id"] for a in asks}) == 1
        request_id = asks[0]["request"]["id"]
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(lambda _: c.post(f"/p/shop/apps/requests/{request_id}/allow"), range(4)))
        assert len(c.get("/p/shop/apps").json()["runs"]) == 1
