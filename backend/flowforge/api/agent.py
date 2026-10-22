"""Connect an agent (D29): the set-up each coding agent needs to start FlowForge's MCP server on this repo, with the
paths filled in, and the agent's last call, which proves the connection works.

GET /agent/connect   {repo, command, agents: {claude, codex, antigravity}, last_call}
"""

from __future__ import annotations

import json
import shlex
import shutil
from typing import Any

from fastapi import APIRouter

from flowforge.agent import LAST_CALL_SETTING
from flowforge.api.scan import repo_path
from flowforge.home import CHECKOUT
from flowforge.state import app_state

router = APIRouter()


def _command(repo: str, db: str) -> list[str]:
    """Until FlowForge is on PyPI (Phase 8), uv runs it from this checkout. Full paths: an agent started from a
    desktop app may not have your shell's PATH."""
    uv = shutil.which("uv") or "uv"
    return [uv, "--directory", str(CHECKOUT), "run", "flowforge", "mcp", "--repo", repo, "--db", db]


@router.get("/agent/connect")
def agent_connect() -> dict[str, Any]:
    s = app_state()
    repo = repo_path(s)
    command = _command(str(repo) if repo else ".", str(s.storage.path.resolve()))
    line = shlex.join(command)
    config = {"mcpServers": {"flowforge": {"command": command[0], "args": command[1:]}}}
    # JSON strings are valid TOML basic strings, Windows backslashes included
    args = ", ".join(map(json.dumps, command[1:]))
    toml = f"[mcp_servers.flowforge]\ncommand = {json.dumps(command[0])}\nargs = [{args}]"
    last = s.storage.setting(LAST_CALL_SETTING)
    return {
        "repo": str(repo) if repo else None,
        "command": command,
        "agents": {
            "claude": {"name": "Claude Code", "how": "terminal", "checked": True,
                       "text": f"claude mcp add flowforge -- {line}"},
            "codex": {"name": "Codex", "how": "terminal", "checked": True,
                      "text": f"codex mcp add flowforge -- {line}",
                      "file": "~/.codex/config.toml",
                      "file_text": toml},
            "antigravity": {"name": "Antigravity", "how": "file", "checked": False,
                            "file": "mcp_config.json (… menu → MCP Servers → Manage MCP Servers → View raw config)",
                            "text": json.dumps(config, indent=2)},
        },
        "last_call": json.loads(last) if last else None,
    }
