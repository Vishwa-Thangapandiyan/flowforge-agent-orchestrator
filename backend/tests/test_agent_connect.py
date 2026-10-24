"""The dashboard's "Connect an agent" page (D29): copy-ready set-up for three agents, and proof the agent called."""

import json
import shlex
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowforge import main
from flowforge.agent import AGENT_CALLS_SETTING
from flowforge.state import app_state

TRIP_PLANNER = Path(__file__).resolve().parents[2] / "examples" / "trip-planner"


@pytest.fixture
def example(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "with space" / "example.db"))
    (tmp_path / "with space").mkdir()
    with TestClient(main.app) as c:
        yield c


def test_each_agent_gets_its_set_up_with_the_paths_filled_in(example, tmp_path):
    got = example.get("/agent/connect").json()
    assert got["repo"] == str(TRIP_PLANNER)
    command = got["command"]
    # the agent starts FlowForge on this repo, with the dashboard's own database (so its checks and yeses apply)
    assert command[-5:] == ["mcp", "--repo", str(TRIP_PLANNER), "--db", str(tmp_path / "with space" / "example.db")]
    claude = got["agents"]["claude"]
    assert claude["how"] == "terminal" and claude["text"].startswith("claude mcp add flowforge -- ")
    assert shlex.split(claude["text"])[5:] == command   # quoted so a path with a space survives
    codex = got["agents"]["codex"]
    assert codex["text"].startswith("codex mcp add flowforge -- ")
    antigravity = got["agents"]["antigravity"]
    config = json.loads(antigravity["text"])
    assert [config["mcpServers"]["flowforge"]["command"], *config["mcpServers"]["flowforge"]["args"]] == command
    assert antigravity["checked"] is False   # its file's place differs between versions: said so on the page
    assert got["last_call"] is None and got["calls"] == []


def test_the_page_shows_the_agents_calls_newest_first(example):
    calls = [{"tool": "get_advice", "repo": "trip-planner", "at": "2026-10-22T10:01:00Z", "got": "3 ways to be faster"},
             {"tool": "get_map", "repo": "trip-planner", "at": "2026-10-22T10:00:00Z", "got": "11 dependencies"}]
    app_state().storage.set_setting(AGENT_CALLS_SETTING, json.dumps(calls))
    got = example.get("/agent/connect").json()
    assert got["calls"] == calls and got["last_call"] == calls[0]


def test_the_preview_is_this_repos_answers(example):
    got = example.get("/agent/preview").json()
    assert got["repo"] == "trip-planner"
    assert [c["tool"] for c in got["cards"]] == ["get_map", "check_health", "get_security_findings", "get_keys",
                                                  "get_flow", "get_advice", "what_changed"]


def test_no_preview_before_a_folder_is_mapped(tmp_path, monkeypatch):
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.delenv("FLOWFORGE_REPO", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "empty.db"))
    with TestClient(main.app) as c:
        assert c.get("/agent/preview").status_code == 404
