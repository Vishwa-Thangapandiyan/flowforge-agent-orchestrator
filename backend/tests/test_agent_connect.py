"""The dashboard's "Connect an agent" page (D29): copy-ready set-up for three agents, and proof the agent called."""

import json
import shlex
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowforge import main
from flowforge.agent import LAST_CALL_SETTING
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
    assert got["last_call"] is None


def test_the_page_shows_the_agents_last_call(example):
    app_state().storage.set_setting(LAST_CALL_SETTING, json.dumps({"tool": "get_advice", "repo": "trip-planner",
                                                                  "at": "2026-10-22T10:00:00Z"}))
    assert example.get("/agent/connect").json()["last_call"] == {"tool": "get_advice", "repo": "trip-planner",
                                                                  "at": "2026-10-22T10:00:00Z"}
