"""MCP servers from config files (D21): .mcp.json, mcp.json, .vscode/.cursor mcp.json, claude_desktop_config.json.

Only the command, its arguments (redacted) and env var *names* are kept. Env values are never read out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from flowforge.scan.urls import clean_url
from flowforge.security.logfilter import REDACTED, SECRET_NAME, Redactor, redact_code

CONFIG_NAMES = frozenset({".mcp.json", "mcp.json", "claude_desktop_config.json"})
_redactor = Redactor()


@dataclass
class Server:
    name: str
    line: int
    command: list[str] = field(default_factory=list)
    env_names: list[str] = field(default_factory=list)


def is_config(rel: str) -> bool:
    return PurePosixPath(rel).name in CONFIG_NAMES


def safe_args(args: list[str]) -> list[str]:
    """Arguments with key-shaped values and the values of key-like flags (--api-key X, TOKEN=X) masked."""
    out: list[str] = []
    for i, arg in enumerate(args):
        if i and SECRET_NAME.search(args[i - 1]) and args[i - 1].startswith("-"):
            out.append(REDACTED)
        elif "=" in arg and SECRET_NAME.search(arg.split("=", 1)[0]):
            out.append(f"{arg.split('=', 1)[0]}={REDACTED}")
        else:
            out.append(redact_code(arg, _redactor))
    return out


def parse(text: str) -> list[Server]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    block = data.get("mcpServers") or data.get("servers") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return []
    lines = text.splitlines()
    servers = []
    for name, spec in block.items():
        if not isinstance(spec, dict):
            continue
        key = f'"{name}"'
        line = next((i for i, raw in enumerate(lines, 1) if raw.lstrip().startswith(key)), 1)
        args = [str(a) for a in spec.get("args", []) if isinstance(a, (str, int, float))]
        command = [str(spec["command"]), *args] if spec.get("command") else []
        if not command and spec.get("url"):   # a remote (HTTP/SSE) server: scheme, host and path only (D21)
            url = clean_url(str(spec["url"]))
            command = [url] if url else []
        env = spec.get("env") if isinstance(spec.get("env"), dict) else {}
        servers.append(Server(name=name, line=line, command=safe_args(command), env_names=sorted(env)))
    return servers
