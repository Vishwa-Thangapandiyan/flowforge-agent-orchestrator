"""MCP tool call with the official `mcp` SDK (D9). Owner: Person C.

params: server  — a command list for a stdio server (default ["uvx", "mcp-server-fetch"])
                  or the name of a server registered with MCPNode(servers={...})
        tool    — e.g. "fetch"
        arguments (dict)
output: {"content": str (text blocks joined), "structured": dict | None}

One connection per server is opened on first use and reused for the whole run
(spawning a process per call is slow). A tool that reports is_error fails the step.
Not cached across runs unless the step sets cache: true (tools can have side effects).
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import Client, MCPError, StdioServerParameters

from flowforge.nodes.base import Node, NodeError, TransientNodeError

DEFAULT_SERVER = ["uvx", "mcp-server-fetch"]


class _Connection:
    """Owns one MCP client inside a dedicated task.

    anyio cancel scopes must be entered and exited by the same task, so the client's
    context manager lives in `_own()` rather than in whichever step happened to open it.
    Steps call tools on the shared client from their own tasks.
    """

    def __init__(self, server: Any) -> None:
        self.server = server
        self.client: Client | None = None
        self._ready = asyncio.Event()
        self._closing = asyncio.Event()
        self._error: BaseException | None = None
        self._task = asyncio.create_task(self._own())

    async def _own(self) -> None:
        try:
            # stdio servers like mcp-server-fetch predate `server/discover`; skip the probe
            mode = "legacy" if isinstance(self.server, StdioServerParameters) else "auto"
            async with Client(self.server, cache=None, mode=mode) as client:
                self.client = client
                self._ready.set()
                await self._closing.wait()
        except Exception as exc:
            self._error = exc
        finally:
            self.client = None
            self._ready.set()

    @property
    def alive(self) -> bool:
        return not self._task.done()

    async def wait_ready(self) -> Client:
        await self._ready.wait()
        if self.client is None:
            raise TransientNodeError(f"could not connect to MCP server: {self._error!r}")
        return self.client

    async def close(self) -> None:
        self._closing.set()
        await self._task


class MCPNode(Node):
    type = "mcp"

    def __init__(self, servers: dict[str, Any] | None = None) -> None:
        self.servers = servers or {}
        self._connections: dict[Any, _Connection] = {}
        self._lock = asyncio.Lock()

    def _resolve_server(self, spec: Any) -> tuple[Any, Any]:
        """(connection key, what to pass to mcp.Client)."""
        if isinstance(spec, str):
            if spec not in self.servers:
                raise NodeError(f"unknown MCP server '{spec}'")
            return spec, self.servers[spec]
        if not spec or not all(isinstance(part, str) for part in spec):
            raise NodeError("params.server must be a server name or a command list")
        return tuple(spec), StdioServerParameters(command=spec[0], args=list(spec[1:]))

    async def _connection(self, spec: Any) -> Client:
        key, server = self._resolve_server(spec)
        async with self._lock:
            conn = self._connections.get(key)
            if conn is None or not conn.alive:
                conn = self._connections[key] = _Connection(server)
        return await conn.wait_ready()

    async def aclose(self) -> None:
        for conn in self._connections.values():
            await conn.close()
        self._connections.clear()

    async def run(self, params: dict[str, Any]) -> Any:
        if "tool" not in params:
            raise NodeError("mcp step needs params.tool")
        client = await self._connection(params.get("server", DEFAULT_SERVER))
        try:
            result = await client.call_tool(params["tool"], params.get("arguments", {}))
        except MCPError as exc:
            raise NodeError(f"MCP error: {exc}") from exc
        except (OSError, EOFError) as exc:
            raise TransientNodeError(f"MCP connection lost: {exc}") from exc

        text = "\n".join(block.text for block in result.content if getattr(block, "type", None) == "text")
        if result.is_error:
            raise NodeError(f"MCP tool '{params['tool']}' failed: {text}")
        return {"content": text, "structured": result.structured_content}
