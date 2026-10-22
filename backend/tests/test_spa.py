"""Serving the dashboard next to the API (D15): HTML navigations get the app, everything else JSON."""

import pytest
from fastapi.testclient import TestClient

from flowforge import main, spa

HTML = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "spa.db"))
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root>APP</div>", encoding="utf-8")
    monkeypatch.setattr(spa, "DIST", dist)
    with TestClient(main.app) as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/runs", "/runs/abc123", "/connectors/nim", "/connectors/new", "/live", "/nope"])
def test_browser_navigations_get_the_app(client, path):
    r = client.get(path, headers=HTML)
    assert r.status_code == 200 and "APP" in r.text and r.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path", ["/runs", "/connectors/nim", "/meta", "/stats/savings"])
def test_api_calls_still_get_json(client, path):
    for accept in ("application/json", "*/*"):
        r = client.get(path, headers={"accept": accept})
        assert r.headers["content-type"].startswith("application/json"), (path, accept)


def test_api_docs_and_classic_are_not_swallowed(client):
    assert "swagger" in client.get("/docs", headers=HTML).text.lower()
    assert "APP" not in client.get("/classic", headers=HTML).text


def test_without_a_build_the_classic_page_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "nobuild.db"))
    monkeypatch.setattr(spa, "DIST", tmp_path / "missing")
    with TestClient(main.app) as client:
        r = client.get("/", headers=HTML)
        assert r.status_code == 200 and r.content == spa.CLASSIC.read_bytes()
        assert client.get("/runs", headers=HTML).headers["content-type"].startswith("application/json")
