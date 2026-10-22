"""MCP tool call with the official `mcp` SDK (D9, D12).

params: server  — a command list for a stdio server (default ["uvx", "mcp-server-fetch"])
                  or the name of a server registered with MCPNode(servers={...});
                  not allowed on a connector node, whose connector fixes the server
        tool    — e.g. "fetch"
        arguments (dict)
output: {"content": str (text blocks joined), "structured": dict | None,
         "blocks": [...]  — only when the result has non-text blocks (D12)}

One connection per server is opened on first use and reused for the whole run
(spawning a process per call is slow). Its tool list is discovered once and every call
is checked against it — unknown tool, or arguments that fail the tool's JSON Schema —
before anything is sent (D12). A tool that reports is_error fails the step.
Not cached across runs unless the step sets cache: true (tools can have side effects).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import mimetypes
import re
from typing import Any

import jsonschema
from mcp import Client, MCPError, StdioServerParameters

from flowforge.connectors.models import MCPConnector
from flowforge.connectors.secrets import SecretRefError, resolve_env
from flowforge.home import flowforge_home
from flowforge.nodes.base import Node, NodeError, TransientNodeError, current_run_id

DEFAULT_SERVER = ["uvx", "mcp-server-fetch"]
INLINE_LIMIT_BYTES = 64 * 1024  # larger binary blocks go to an artifact file (D12)
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class _Connection:
    """Owns one MCP client inside a dedicated task.

    anyio cancel scopes must be entered and exited by the same task, so the client's
    context manager lives in `_own()` rather than in whichever step happened to open it.
    Steps call tools on the shared client from their own tasks.
    """

    def __init__(self, server: Any) -> None:
        self.server = server
        self.client: Client | None = None
        self.tools: list[dict[str, Any]] | None = None  # discovered once per connection
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


def check_call(tools: list[dict[str, Any]], tool: str, arguments: Any) -> str | None:
    """Why calling `tool` with `arguments` would be wrong, or None if it's fine (D12).
    `arguments=None` checks the tool name only (used when arguments hold templates)."""
    by_name = {t["name"]: t for t in tools}
    if tool not in by_name:
        return f"Unknown tool '{tool}'; this server has: {', '.join(sorted(by_name)) or 'no tools'}"
    if arguments is None:
        return None
    schema = by_name[tool].get("input_schema") or {}
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(arguments), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(map(str, first.path))
        at = f" (at '{where}')" if where else ""
        return f"arguments for tool '{tool}' don't match its schema: {first.message}{at}"
    return None


class MCPNode(Node):
    type = "mcp"

    def __init__(self, servers: dict[str, Any] | None = None, default_server: Any = None) -> None:
        self.servers = servers or {}
        self.default_server = default_server  # used when params.server is absent; None = DEFAULT_SERVER
        self.connector: MCPConnector | None = None
        self._connections: dict[Any, _Connection] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def from_connector(cls, connector: MCPConnector) -> MCPNode:
        node = cls()
        node.connector = connector
        node.connector_id = connector.id
        node.fallback = connector.fallback
        node.rate_limit_key = connector.id
        return node

    def _connector_server(self) -> StdioServerParameters:
        """Server parameters for the connector; secret env values are resolved here, at spawn (D12)."""
        assert self.connector is not None
        conn = self.connector.connection
        try:
            env = resolve_env(conn.env, conn.env_refs)
        except SecretRefError as exc:
            raise NodeError(f"MCP connector '{self.connector.id}': {exc}") from exc
        return StdioServerParameters(command=conn.command, args=list(conn.args), env=env or None)

    def _resolve_server(self, spec: Any) -> tuple[Any, Any]:
        """(connection key, what to pass to mcp.Client)."""
        if self.connector is not None:
            if spec is not None:
                raise NodeError(f"connector '{self.connector.id}' fixes the server; remove params.server")
            return ("connector", self.connector.id), self._connector_server()
        if spec is None:
            if self.default_server is None:
                spec = DEFAULT_SERVER
            elif isinstance(self.default_server, list):
                spec = self.default_server
            else:
                return "__default__", self.default_server
        if isinstance(spec, str):
            if spec not in self.servers:
                raise NodeError(f"unknown MCP server '{spec}'")
            return spec, self.servers[spec]
        if not spec or not all(isinstance(part, str) for part in spec):
            raise NodeError("params.server must be a server name or a command list")
        return tuple(spec), StdioServerParameters(command=spec[0], args=list(spec[1:]))

    async def _connection(self, spec: Any) -> tuple[_Connection, Client]:
        key, server = self._resolve_server(spec)
        async with self._lock:
            conn = self._connections.get(key)
            if conn is None or not conn.alive:
                conn = self._connections[key] = _Connection(server)
        return conn, await conn.wait_ready()

    async def aclose(self) -> None:
        for conn in self._connections.values():
            await conn.close()
        self._connections.clear()

    async def list_tools(self, server: Any = None) -> list[dict[str, Any]]:
        """Every tool the server offers: name, description, JSON input schema (D12)."""
        conn, client = await self._connection(server)
        if conn.tools is None:
            tools: list[dict[str, Any]] = []
            cursor: str | None = None
            try:
                while True:
                    page = await client.list_tools(cursor=cursor)
                    tools += [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
                              for t in page.tools]
                    if not (cursor := page.next_cursor):
                        break
            except MCPError as exc:
                raise NodeError(f"MCP error listing tools: {exc}") from exc
            except (OSError, EOFError) as exc:
                raise TransientNodeError(f"MCP connection lost: {exc}") from exc
            conn.tools = tools
        return conn.tools

    async def run(self, params: dict[str, Any]) -> Any:
        if "tool" not in params:
            raise NodeError("mcp step needs params.tool")
        server = params.get("server")
        arguments = params.get("arguments", {})
        problem = check_call(await self.list_tools(server), params["tool"], arguments)
        if problem:
            raise NodeError(problem)
        _, client = await self._connection(server)
        try:
            result = await client.call_tool(params["tool"], arguments)
        except MCPError as exc:
            raise NodeError(f"MCP error: {exc}") from exc
        except (OSError, EOFError) as exc:
            raise TransientNodeError(f"MCP connection lost: {exc}") from exc

        text = "\n".join(block.text for block in result.content if getattr(block, "type", None) == "text")
        if result.is_error:
            raise NodeError(f"MCP tool '{params['tool']}' failed: {text}")
        output: dict[str, Any] = {"content": text, "structured": result.structured_content}
        blocks = [b for b in map(_convert_block, result.content) if b is not None]
        if blocks:
            output["blocks"] = blocks
        return output


# --- non-text result blocks (D12) ----------------------------------------------------------------

def _convert_block(block: Any) -> dict[str, Any] | None:
    kind = getattr(block, "type", None)
    if kind == "text":
        return None
    if kind in ("image", "audio"):
        return _binary(kind, block.mime_type, base64.b64decode(block.data))
    if kind == "resource_link":
        return {"kind": "resource", "uri": str(block.uri), "name": block.name}
    if kind == "resource":
        res = block.resource
        if getattr(res, "text", None) is not None:
            return {"kind": "text", "uri": str(res.uri), "text": res.text}
        mime = res.mime_type or "application/octet-stream"
        major = mime.split("/", 1)[0]
        return _binary(major if major in ("image", "audio", "video") else "file", mime, base64.b64decode(res.blob))
    return {"kind": "unknown", "type": str(kind)}


def _binary(kind: str, mime: str | None, data: bytes) -> dict[str, Any]:
    mime = mime or "application/octet-stream"
    if len(data) <= INLINE_LIMIT_BYTES:
        return {"kind": kind, "mime": mime, "data_b64": base64.b64encode(data).decode()}
    run_id = current_run_id.get()
    folder = flowforge_home() / "artifacts" / (run_id if run_id and _RUN_ID.match(run_id) else "adhoc")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{hashlib.sha256(data).hexdigest()}{mimetypes.guess_extension(mime) or '.bin'}"
    if not path.exists():
        path.write_bytes(data)
    return {"kind": kind, "mime": mime, "path": str(path), "bytes": len(data)}
