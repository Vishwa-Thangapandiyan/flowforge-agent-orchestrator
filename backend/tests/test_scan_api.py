"""Scanning through the API and the CLI (D21): choose a folder, draw its map, re-scan, switch folders."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowforge import cli, main

FAKE_KEY = "sk_test_FAKEFAKE12345678"
TRIP_PLANNER = Path(__file__).resolve().parents[2] / "examples" / "trip-planner"


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def real(tmp_path, monkeypatch):
    """A real (not example) FlowForge on an empty database. Yields a function that starts a client."""
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.delenv("FLOWFORGE_REPO", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "real.db"))
    return lambda: TestClient(main.app)


@pytest.fixture
def repo(tmp_path):
    return write(tmp_path / "shop", {
        "app.py": f'URL = "https://api.weather.test/v1"\nKEY = "{FAKE_KEY}"\n',
        "pay.py": "import stripe\n",
    })


def test_scanning_a_folder_draws_its_dependency_map(real, repo):
    with real() as c:
        assert c.get("/scan").json() == {"repo": None, "name": None, "example": False, "summary": None}
        r = c.post("/scan", json={"path": str(repo)})
        assert r.status_code == 201
        assert r.json()["name"] == "shop" and r.json()["version"] == 1
        f = c.get("/flow").json()
        assert f["available"] and f["kind"] == "dependencies"
        assert {"api-api-weather-test", "api-stripe"} <= {n["id"] for n in f["nodes"]}
        summary = c.get("/scan").json()["summary"]
        assert summary == {"files": 2, "dependencies": 2, "unconfirmed": 0,
                           "kinds": {"api": 2}}


def test_the_chosen_folder_survives_a_restart_and_rescans(real, repo):
    with real() as c:
        c.post("/scan", json={"path": str(repo)})
    write(repo, {"maps.py": 'TILES = "https://api.tiles.test/v2"\n'})
    with real() as c:
        assert c.get("/scan").json()["repo"] == str(repo.resolve())
        pending = c.post("/flow/recheck").json()
        assert [ch["type"] for ch in pending["changes"]] == ["add"]


def test_a_different_folder_needs_replace_and_starts_fresh(real, repo, tmp_path):
    other = write(tmp_path / "blog", {"feed.py": 'FEED = "https://api.feeds.test/v1"\n'})
    with real() as c:
        c.post("/scan", json={"path": str(repo)})
        c.post("/flow/overrides", json={"op": "hide", "node": "api-stripe"})
        r = c.post("/scan", json={"path": str(other)})
        assert r.status_code == 409 and "shop" in r.json()["detail"]
        r = c.post("/scan", json={"path": str(other), "replace": True})
        assert r.status_code == 201 and r.json()["version"] == 1
        f = c.get("/flow").json()
        assert {n["id"] for n in f["nodes"]} == {"app", "api-api-feeds-test"} and f["counts"]["edits"] == 0


def test_a_path_that_is_not_a_folder_is_refused(real, tmp_path):
    with real() as c:
        assert c.post("/scan", json={"path": str(tmp_path / "nowhere")}).status_code == 422
        (tmp_path / "file.txt").write_text("x")
        assert c.post("/scan", json={"path": str(tmp_path / "file.txt")}).status_code == 422
        assert c.post("/scan", json={"path": ""}).status_code == 422


def test_example_mode_scans_the_sample_app_and_refuses_other_folders(tmp_path, monkeypatch, repo):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    with TestClient(main.app) as c:
        assert c.get("/scan").json()["name"] == "trip-planner"
        f = c.get("/flow").json()
        assert f["kind"] == "dependencies" and "llm-ollama" in {n["id"] for n in f["nodes"]}
        assert c.post("/scan", json={"path": str(repo)}).status_code == 409


def test_no_scan_or_map_response_carries_a_key(real, repo):
    with real() as c:
        bodies = [c.post("/scan", json={"path": str(repo)}).text]
        bodies += [c.get(p).text for p in ("/scan", "/flow", "/flow?layer=planner", "/flow/analysis", "/flow/versions")]
    assert all(FAKE_KEY not in b for b in bodies)


def test_the_cli_prints_a_scan_as_json(capsys):
    cli.main(["scan", str(TRIP_PLANNER)])
    out = json.loads(capsys.readouterr().out)
    assert out["root"] == "trip-planner" and len(out["dependencies"]) == 12
    assert "AIzaFAKE" not in json.dumps(out)


def test_the_cli_refuses_a_missing_folder(capsys):
    with pytest.raises(SystemExit) as exit_:
        cli.main(["scan", "/no/such/folder"])
    assert exit_.value.code == 2 and "not a folder" in capsys.readouterr().err


def test_the_cli_asks_for_a_folder_when_none_is_given(capsys):
    with pytest.raises(SystemExit) as exit_:
        cli.main(["scan"])
    assert exit_.value.code == 2 and "name the folder" in capsys.readouterr().err


def test_repo_from_the_cli_is_mapped_at_start_and_a_switch_needs_replace(real, repo, tmp_path, monkeypatch):
    other = write(tmp_path / "blog", {"feed.py": 'FEED = "https://api.feeds.test/v1"\n'})
    monkeypatch.setenv("FLOWFORGE_REPO", str(repo))
    with real() as c:
        assert "api-stripe" in {n["id"] for n in c.get("/flow").json()["nodes"]}   # drawn at start-up
    monkeypatch.setenv("FLOWFORGE_REPO", str(other))
    with pytest.raises(RuntimeError, match="--replace"):
        with real():
            pass
    monkeypatch.setenv("FLOWFORGE_REPO_REPLACE", "1")
    with real() as c:
        assert {n["id"] for n in c.get("/flow").json()["nodes"]} == {"app", "api-api-feeds-test"}


def test_a_key_in_the_repo_reaches_no_byte_of_the_database_and_no_log(real, repo, tmp_path, caplog):
    caplog.set_level("DEBUG")
    with real() as c:
        c.post("/scan", json={"path": str(repo)})
        c.get("/flow")
        c.post("/flow/recheck")
    assert FAKE_KEY.encode() not in (tmp_path / "real.db").read_bytes()
    assert FAKE_KEY not in caplog.text
