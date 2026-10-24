"""Settings and the welcome (D40): one settings file with no secret in it, what Settings shows for every project, taking
back a project's yeses or check history, pairing the agent once, and an update check only when asked. Offline; fake
keys only."""

import json
import textwrap
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from flowforge import home, main, settings
from flowforge.agent import AGENT_CALLS_SETTING
from flowforge.api import settings as settings_api
from flowforge.api.agent import server_command
from flowforge.api.checks import CONFIRMED_SETTING
from flowforge.projects import Projects
from flowforge.security.keystore import KeyStore
from flowforge.storage import Storage

FAKE = "sk_test_FAKEFAKE12345678"
LOCAL, HERE = "http://127.0.0.1:8000", ("127.0.0.1", 50000)


def app_folder(root: Path, name: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "app.py").write_text(textwrap.dedent("""\
        import os
        import httpx

        KEY = os.environ["SHOP_TOKEN"]

        def go():
            return httpx.get("https://api.shop.test/v1")
    """))
    return folder


@pytest.fixture
def two(tmp_path, monkeypatch):
    shop, blog = app_folder(tmp_path, "shop"), app_folder(tmp_path, "blog")
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "flowforge.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(shop))
    return shop, blog


def client():
    return TestClient(main.app, base_url=LOCAL, client=HERE)


# the settings file

def test_settings_start_empty_and_keep_what_is_set():
    assert settings.load() == settings.Settings()
    assert settings.load().welcome_done is False and settings.load().map_style is None
    settings.save({"welcome_done": True, "map_style": "metro"})
    assert settings.load().welcome_done is True and settings.load().map_style == "metro"
    assert json.loads((home.flowforge_home() / "settings.json").read_text()) == {"welcome_done": True,
                                                                                 "map_style": "metro"}


@pytest.mark.parametrize("changes", [{"map_style": "neon"}, {"api_key": FAKE}, {"welcome_done": "yes please"}])
def test_settings_refuse_what_they_dont_know(changes):
    with pytest.raises(ValueError):
        settings.save(changes)
    assert not (home.flowforge_home() / "settings.json").exists()


def test_a_damaged_settings_file_reads_as_the_defaults():
    home.flowforge_home().mkdir(parents=True, exist_ok=True)
    (home.flowforge_home() / "settings.json").write_text("{not json")
    assert settings.load() == settings.Settings()


# what Settings shows

def test_settings_show_every_project_and_nothing_secret(two):
    shop, blog = two
    KeyStore(shop).add("SHOP_TOKEN", FAKE)
    with client() as c:
        assert c.post("/projects", json={"path": str(blog)}).status_code == 201
        got = c.get("/settings")
    assert got.status_code == 200 and FAKE not in got.text
    data = got.json()
    assert data["welcome_done"] is False and data["version"] == home.version()
    assert data["home"] == str(home.flowforge_home())
    assert {p["name"] for p in data["projects"]} == {"shop", "blog"}
    assert all(p["size_bytes"] > 0 for p in data["projects"]) and data["total_bytes"] >= sum(
        p["size_bytes"] for p in data["projects"])
    assert data["vault"] == {"lock": "none", "store": "file"}
    assert data["agent"]["connected"] is False and data["agent"]["last_call"] is None


def test_the_agent_counts_as_connected_once_it_asked_about_any_project(two):
    shop, blog = two
    with client() as c:
        c.post("/projects", json={"path": str(blog)})
        blog_db = Projects().by_folder(blog).db
        Storage(Path(blog_db)).set_setting(AGENT_CALLS_SETTING, json.dumps(
            [{"tool": "get_map", "repo": "blog", "at": "2026-10-24T10:00:00+00:00", "got": "1 dependency"}]))
        agent = c.get("/settings").json()["agent"]
    assert agent["connected"] is True and agent["last_call"]["repo"] == "blog"


def test_pairing_once_names_no_folder_and_no_database(monkeypatch):
    for kind in ("checkout", "uvx", "pip"):
        monkeypatch.setattr(home, "install_kind", lambda kind=kind: kind)
        cmd = server_command(None, None)
        assert cmd[-1] == "mcp" and "--repo" not in cmd and "--db" not in cmd, kind
    monkeypatch.setattr(home, "install_kind", lambda: "pip")
    assert server_command("/home/me/app", "/home/me/x.db")[-5:] == ["mcp", "--repo", "/home/me/app", "--db",
                                                                    "/home/me/x.db"]


def test_settings_give_each_agent_the_pair_once_line_with_flowforges_home(two):
    with client() as c:
        agents = c.get("/settings").json()["agent"]["agents"]
    claude, codex, antigravity = agents["claude"], agents["codex"], agents["antigravity"]
    assert claude["text"].startswith("claude mcp add flowforge") and claude["text"].endswith(" mcp")
    assert "--repo" not in claude["text"] + codex["text"] + antigravity["text"]
    home_dir = str(home.flowforge_home())   # the tests' FLOWFORGE_HOME isn't the default, so the agent is told it
    assert f"FLOWFORGE_HOME={home_dir}" in claude["text"] and f"FLOWFORGE_HOME={home_dir}" in codex["text"]
    assert json.loads(antigravity["text"])["mcpServers"]["flowforge"]["env"] == {"FLOWFORGE_HOME": home_dir}
    assert "[mcp_servers.flowforge.env]" in codex["file_text"]


# changing settings

def test_finishing_the_welcome_and_a_map_style_are_kept(two):
    with client() as c:
        r = c.patch("/settings", json={"welcome_done": True, "map_style": "boxed"})
        assert r.status_code == 200 and r.json()["welcome_done"] is True
        assert c.get("/settings").json()["map_style"] == "boxed"
        assert c.patch("/settings", json={"map_style": "neon"}).status_code == 422
        assert c.patch("/settings", json={"theme_password": "x"}).status_code == 422


def test_taking_back_yeses_and_clearing_checks_touch_one_project_only(two):
    shop, blog = two
    with client() as c:
        c.post("/projects", json={"path": str(blog)})
        dbs = {p.name: Storage(Path(p.db)) for p in Projects().list()}
        for db in dbs.values():
            db.set_setting(CONFIRMED_SETTING, json.dumps(["uvx mcp-server-time"]))
            db.add_checks("run-1", [{"id": "api-shop-test", "kind": "api", "status": "up", "latency_ms": 12,
                                     "summary": "up", "detail": {}}])
        listed = {p["name"]: p for p in c.get("/settings").json()["projects"]}
        assert listed["shop"]["confirmed"] == ["uvx mcp-server-time"] and listed["shop"]["checks"] == 1
        blog_id = listed["blog"]["id"]
        assert c.delete(f"/projects/{blog_id}/confirmed").json() == {"id": blog_id, "confirmed": []}
        assert c.delete(f"/projects/{blog_id}/checks").json() == {"id": blog_id, "checks": 0}
        listed = {p["name"]: p for p in c.get("/settings").json()["projects"]}
    assert listed["blog"]["confirmed"] == [] and listed["blog"]["checks"] == 0
    assert listed["shop"]["confirmed"] == ["uvx mcp-server-time"] and listed["shop"]["checks"] == 1


def test_an_unknown_project_is_a_404(two):
    with client() as c:
        assert c.delete("/projects/nope/checks").status_code == 404
        assert c.delete("/projects/nope/confirmed").status_code == 404


@pytest.mark.parametrize("headers", [{"host": "evil.test"}, {"host": "127.0.0.1:8000", "origin": "http://evil.test"}])
def test_only_the_dashboard_on_this_machine_changes_settings(two, headers):
    with client() as c:
        assert c.patch("/settings", json={"welcome_done": True}, headers=headers).status_code == 403
        assert c.delete("/projects/shop/checks", headers=headers).status_code == 403
        assert c.post("/settings/update-check", headers=headers).status_code == 403
    assert settings.load().welcome_done is False


# the update check: one request, only when asked

def test_no_request_is_made_unless_the_update_check_is_pressed(two, monkeypatch):
    seen = []
    monkeypatch.setattr(settings_api, "UPDATE_TRANSPORT", httpx.MockTransport(lambda r: seen.append(r) or
                                                                              httpx.Response(500)))
    with client() as c:
        c.get("/settings")
        c.patch("/settings", json={"welcome_done": True})
    assert seen == []


def test_the_update_check_compares_with_pypi(two, monkeypatch):
    seen = []

    def pypi(request):
        seen.append(request)
        return httpx.Response(200, json={"info": {"version": "9.9.0"}})

    monkeypatch.setattr(settings_api, "UPDATE_TRANSPORT", httpx.MockTransport(pypi))
    monkeypatch.setattr(home, "version", lambda: "0.3.0")
    with client() as c:
        got = c.post("/settings/update-check").json()
    assert got == {"current": "0.3.0", "latest": "9.9.0", "newer": True}
    assert [str(r.url) for r in seen] == ["https://pypi.org/pypi/flowforge-map/json"]
    assert "cookie" not in seen[0].headers and "authorization" not in seen[0].headers


def test_the_update_check_says_so_when_pypi_cant_be_reached(two, monkeypatch):
    def down(request):
        raise httpx.ConnectError("no network", request=request)

    monkeypatch.setattr(settings_api, "UPDATE_TRANSPORT", httpx.MockTransport(down))
    with client() as c:
        got = c.post("/settings/update-check").json()
    assert got["latest"] is None and got["newer"] is False and "pypi.org" in got["error"]


def test_the_same_version_is_not_newer(two, monkeypatch):
    monkeypatch.setattr(settings_api, "UPDATE_TRANSPORT",
                        httpx.MockTransport(lambda r: httpx.Response(200, json={"info": {"version": "0.3.0"}})))
    monkeypatch.setattr(home, "version", lambda: "0.3.0")
    with client() as c:
        assert c.post("/settings/update-check").json()["newer"] is False
