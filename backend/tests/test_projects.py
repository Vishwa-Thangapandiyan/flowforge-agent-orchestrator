"""Projects (D39): a list of every project, one database each, and each request routed to its project by `/p/<id>/`.
Two projects never share a map, a key, an issue or a check. Fake keys only."""

import json
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowforge import main
from flowforge.projects import EXAMPLE_ID, Projects
from flowforge.security.keystore import KeyStore

FAKE = "sk_test_FAKEFAKE12345678"
LOCAL, HERE = "http://127.0.0.1:8000", ("127.0.0.1", 50000)


def app_folder(root: Path, name: str, url: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "app.py").write_text(textwrap.dedent(f"""\
        import os
        import httpx

        KEY = os.environ["{name.upper().replace('-', '_')}_TOKEN"]

        def go():
            return httpx.get("{url}")
    """))
    return folder


# the registry

def test_a_folder_becomes_a_project_once_with_a_stable_id(tmp_path):
    reg = Projects()
    shop = app_folder(tmp_path, "shop", "https://api.shop.test/v1")
    first = reg.add(shop)
    assert first.id == "shop" and first.name == "shop" and Path(first.path) == shop.resolve()
    assert reg.add(shop).id == "shop"                                   # the same folder: the same project
    other = app_folder(tmp_path / "elsewhere", "shop", "https://api.other.test")
    assert reg.add(other).id == "shop-2"                                # same name, another folder
    assert [p.id for p in Projects().list()] == ["shop", "shop-2"]      # kept on disk


def test_rename_remove_and_find_by_folder(tmp_path):
    reg = Projects()
    shop = reg.add(app_folder(tmp_path, "shop", "https://a.test"))
    reg.rename(shop.id, "My shop")
    assert reg.get("shop").name == "My shop" and reg.find("My shop").id == "shop"
    assert reg.for_folder(Path(shop.path) / "src" / "deep").id == "shop"   # the agent works inside it
    assert reg.for_folder(tmp_path) is None
    reg.remove("shop")
    assert reg.get("shop") is None


def test_each_new_project_gets_its_own_database(tmp_path):
    reg = Projects()
    a = reg.add(app_folder(tmp_path, "a", "https://a.test"))
    b = reg.add(app_folder(tmp_path, "b", "https://b.test"))
    assert a.db != b.db and Path(a.db).parent == Path(b.db).parent


# the API: one process, many projects

@pytest.fixture
def two(tmp_path, monkeypatch):
    shop = app_folder(tmp_path, "shop", "https://api.shop.test/v1")
    blog = app_folder(tmp_path, "blog", "https://api.blog.test/v2")
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "flowforge.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(shop))
    return shop, blog


def node_ids(c, prefix=""):
    return {n["id"] for n in c.get(f"{prefix}/flow").json()["nodes"]}


def test_the_folder_flowforge_started_on_is_a_project_and_the_default(two):
    shop, _ = two
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        got = c.get("/projects").json()
        assert [p["id"] for p in got["projects"]] == ["shop"] and got["default"] == "shop"
        assert got["projects"][0]["path"] == str(shop.resolve())
        assert node_ids(c) == node_ids(c, "/p/shop")                 # no prefix = the default project


def test_a_second_project_has_its_own_map_keys_and_issues(two):
    shop, blog = two
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        added = c.post("/projects", json={"path": str(blog)})
        assert added.status_code == 201 and added.json()["id"] == "blog"
        assert "api-api-blog-test" in node_ids(c, "/p/blog") and "api-api-blog-test" not in node_ids(c)
        assert "api-api-shop-test" in node_ids(c) and "api-api-shop-test" not in node_ids(c, "/p/blog")
        assert c.put("/p/blog/keys/BLOG_TOKEN", json={"value": FAKE}).status_code == 200
        shop_keys = {k["name"]: k["status"] for k in c.get("/keys").json()["keys"]}
        blog_keys = {k["name"]: k["status"] for k in c.get("/p/blog/keys").json()["keys"]}
        assert blog_keys == {"BLOG_TOKEN": "saved"} and shop_keys == {"SHOP_TOKEN": "missing"}
        assert c.get("/p/blog/scan").json()["repo"] == str(blog.resolve())
        listed = {p["id"]: p for p in c.get("/projects").json()["projects"]}
        assert set(listed) == {"shop", "blog"}
        assert listed["blog"]["summary"]["dependencies"] == 1 and listed["blog"]["summary"]["keys_missing"] == 0
        assert listed["shop"]["summary"]["keys_missing"] == 1
    assert KeyStore(blog).names() == ["BLOG_TOKEN"] and KeyStore(shop).names() == []


def test_adding_the_same_folder_twice_opens_the_same_project(two):
    _, blog = two
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        first = c.post("/projects", json={"path": str(blog)}).json()["id"]
        again = c.post("/projects", json={"path": str(blog)})
        assert again.status_code == 200 and again.json()["id"] == first


def test_an_unknown_project_or_folder_is_refused(two, tmp_path):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        assert c.get("/p/nope/flow").status_code == 404
        assert c.post("/projects", json={"path": str(tmp_path / "missing")}).status_code == 422


def test_rename_and_remove_a_project_never_touch_its_folder(two):
    _, blog = two
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        c.post("/projects", json={"path": str(blog)})
        assert c.patch("/projects/blog", json={"name": "My blog"}).json()["name"] == "My blog"
        db = Path(next(p for p in Projects().list() if p.id == "blog").db)
        assert db.is_file()
        assert c.delete("/projects/blog").json() == {"id": "blog", "removed": True}
        assert [p["id"] for p in c.get("/projects").json()["projects"]] == ["shop"]
        assert c.get("/p/blog/flow").status_code == 404
    assert not db.exists() and (blog / "app.py").is_file()               # FlowForge's copy gone, your code kept


def test_removing_the_default_project_hands_over_to_another_then_to_none(two, tmp_path):
    """Codex review: any project can be removed (D39). The next one opened becomes the default; with none left,
    the map offers to scan a folder."""
    _, blog = two
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        c.post("/projects", json={"path": str(blog)})
        assert c.delete("/projects/shop").json() == {"id": "shop", "removed": True}
        listed = c.get("/projects").json()
        assert [p["id"] for p in listed["projects"]] == ["blog"] and listed["default"] == "blog"
        assert "api-api-blog-test" in node_ids(c)                       # no prefix: now blog
        assert c.delete("/projects/blog").json()["removed"] is True
        assert c.get("/projects").json() == {**c.get("/projects").json(), "default": None, "projects": []}
        assert c.get("/scan").json()["repo"] is None                     # a blank FlowForge: scan a folder
        assert c.get("/flow").json()["available"] is False
    assert not (tmp_path / "flowforge.db").exists()


def test_project_changes_answer_only_to_this_machine(two):
    _, blog = two
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        assert c.post("/projects", json={"path": str(blog)}, headers={"host": "evil.test"}).status_code == 403


def test_the_example_is_a_built_in_project(two):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        listed = c.get("/projects").json()
        assert listed["example"]["id"] == EXAMPLE_ID
        assert c.get(f"/p/{EXAMPLE_ID}/meta").json()["example"] is True
        assert "llm-ollama" in node_ids(c, f"/p/{EXAMPLE_ID}")
        assert c.get("/meta").json()["example"] is False                # the default is still yours


def test_an_older_database_becomes_the_first_project_where_it_lies(tmp_path, monkeypatch):
    """D39: a database made before projects (with its repo setting) is listed as is; nothing moves."""
    shop = app_folder(tmp_path, "shop", "https://api.shop.test/v1")
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "old.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(shop))
    with TestClient(main.app, base_url=LOCAL, client=HERE):
        pass                                                           # made the old way: one db, one repo
    (Projects().path).unlink()                                         # as if projects.json never existed
    monkeypatch.delenv("FLOWFORGE_REPO")
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        listed = c.get("/projects").json()["projects"]
    assert [(p["id"], p["path"]) for p in listed] == [("shop", str(shop.resolve()))]
    assert json.loads(Projects().path.read_text())[0]["db"] == str((tmp_path / "old.db").resolve())


def test_a_saved_key_in_one_project_appears_in_no_answer_of_any(two):
    _, blog = two
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        c.post("/projects", json={"path": str(blog)})
        c.put("/p/blog/keys/BLOG_TOKEN", json={"value": FAKE})
        paths = [r.path for r in main.app.routes if "GET" in getattr(r, "methods", ()) and "{" not in r.path]
        answers = [c.get(p).text for p in paths] + [c.get(f"/p/blog{p}").text for p in paths]
    assert all(FAKE not in a for a in answers)
