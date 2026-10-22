"""MCP servers from .mcp.json: local time, page fetch, saving files, and a broken currency server."""

from __future__ import annotations

import json
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import HERE

SERVERS: dict[str, dict[str, Any]] = json.loads((HERE / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]


async def call(server: str, tool: str, arguments: dict[str, Any]) -> str:
    """Start one server from .mcp.json, call one tool, return its text."""
    spec = SERVERS[server]
    params = StdioServerParameters(command=spec["command"], args=spec.get("args", []), cwd=str(HERE))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(tool, arguments)
    text = "\n".join(block.text for block in result.content if getattr(block, "type", "") == "text")
    if result.is_error:
        raise RuntimeError(text or f"{server}.{tool} failed")
    return text
