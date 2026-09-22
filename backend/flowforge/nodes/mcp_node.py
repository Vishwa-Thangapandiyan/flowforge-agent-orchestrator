"""MCP tool call over stdio with the official `mcp` SDK (D9). Owner: Person C.

params: server (command list, default ["uvx", "mcp-server-fetch"]), tool (e.g. "fetch"), arguments (dict)
output: {"content": [text blocks joined], "is_error": bool}

Reuse one ClientSession per server command for the whole run (spawning a
process per call is slow). Not cached across runs unless step.cache is true.
"""

from __future__ import annotations

from typing import Any

from flowforge.nodes.base import Node


class MCPNode(Node):
    type = "mcp"

    async def run(self, params: dict[str, Any]) -> Any:
        raise NotImplementedError
