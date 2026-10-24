"""Connect an agent (D29): the set-up each coding agent needs to start FlowForge's MCP server on this repo, with the
paths filled in, and the agent's calls, which prove the connection works. The preview is what each tool would answer
about this repo now (D30).

GET /agent/connect   {repo, command, agents: {claude, codex, antigravity}, last_call, calls}
GET /agent/preview   {repo, cards: [{tool, headline, sub, tone}]}
"""

from __future__ import annotations

import json
import shlex
import shutil
import sys
from typing import Any

from fastapi import APIRouter, HTTPException

from flowforge import home
from flowforge.agent import AGENT_CALLS_SETTING, preview
from flowforge.api.scan import repo_path
from flowforge.state import app_state

router = APIRouter()


def server_command(repo: str | None, db: str | None) -> list[str]:
    """How the agent starts FlowForge's MCP server, matching how FlowForge was installed (D34): from the checkout
    through uv, through uvx with the version pinned (as FlowForge advises for MCP servers, D31), or the same Python.
    Full paths: an agent started from a desktop app may not have your shell's PATH. With no folder it serves every
    project: the agent is paired once (D39, D40)."""
    tail = ["mcp", "--repo", repo, "--db", db] if repo else ["mcp"]
    kind = home.install_kind()
    if kind == "checkout":
        return [shutil.which("uv") or "uv", "--directory", str(home.CHECKOUT), "run", "flowforge", *tail]
    if kind == "uvx":
        return [shutil.which("uvx") or "uvx", f"{home.DIST_NAME}=={home.version()}", *tail]
    return [sys.executable, "-m", "flowforge.cli", *tail]


def _command(repo: str, db: str) -> list[str]:
    return server_command(repo, db)


def agents_for(command: list[str], env: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Each coding agent's set-up for `command`: a line to paste, or a file to edit. `env` is passed to the server
    (FLOWFORGE_HOME when it isn't the default, so the agent finds the same projects)."""
    env = env or {}
    line = shlex.join(command)
    flags = "".join(f" -e {shlex.quote(f'{k}={v}')}" for k, v in env.items())
    codex_flags = "".join(f" --env {shlex.quote(f'{k}={v}')}" for k, v in env.items())
    server: dict[str, Any] = {"command": command[0], "args": command[1:]}
    if env:
        server["env"] = env
    # JSON strings are valid TOML basic strings, Windows backslashes included
    args = ", ".join(map(json.dumps, command[1:]))
    toml = f"[mcp_servers.flowforge]\ncommand = {json.dumps(command[0])}\nargs = [{args}]"
    if env:
        toml += "\n\n[mcp_servers.flowforge.env]\n" + "\n".join(f"{k} = {json.dumps(v)}" for k, v in env.items())
    return {
        "claude": {"name": "Claude Code", "how": "terminal", "checked": True,
                   "text": f"claude mcp add flowforge{flags} -- {line}"},
        "codex": {"name": "Codex", "how": "terminal", "checked": True,
                  "text": f"codex mcp add flowforge{codex_flags} -- {line}",
                  "file": "~/.codex/config.toml", "file_text": toml},
        "antigravity": {"name": "Antigravity", "how": "file", "checked": False,
                        "file": "mcp_config.json (… menu → MCP Servers → Manage MCP Servers → View raw config)",
                        "text": json.dumps({"mcpServers": {"flowforge": server}}, indent=2)},
    }


@router.get("/agent/connect")
def agent_connect() -> dict[str, Any]:
    s = app_state()
    repo = repo_path(s)
    command = _command(str(repo) if repo else ".", str(s.storage.path.resolve()))
    try:
        calls = json.loads(s.storage.setting(AGENT_CALLS_SETTING) or "[]")
    except ValueError:
        calls = []
    return {
        "repo": str(repo) if repo else None,
        "command": command,
        "agents": agents_for(command),
        "last_call": calls[0] if calls else None,
        "calls": calls,
    }


@router.get("/agent/preview")
def agent_preview() -> dict[str, Any]:
    s = app_state()
    repo = repo_path(s)
    if repo is None:
        raise HTTPException(404, "No folder mapped yet: scan one first")
    return preview(repo, s.storage)
