"""The `check` step (D24): one health check per step, so the scheduler runs a check run like any other."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from flowforge.checks import CheckTarget, check, new_client
from flowforge.nodes.base import Node, NodeError

# MCP servers are processes; at most this many start together (D24). The scheduler's slots are per step type and
# every check is one type, so the limit lives here; check_workflow() gives MCP steps a timeout that covers the wait.
MCP_AT_ONCE = 3


class CheckNode(Node):
    type = "check"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport   # tests answer through a MockTransport
        self._http: httpx.AsyncClient | None = None
        self._mcp = asyncio.Semaphore(MCP_AT_ONCE)

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = new_client(self._transport)
        return self._http

    async def run(self, params: dict[str, Any]) -> Any:
        """params: `target` (a CheckTarget) and `root` (the scanned folder). A dependency that is down is a
        result; only a check that can't run at all fails the step."""
        try:
            target = CheckTarget.model_validate(params["target"])
            root = Path(params["root"])
        except (KeyError, ValueError) as exc:
            raise NodeError(f"check step: {exc}") from exc
        if target.kind == "mcp":
            async with self._mcp:
                result = await check(target, root, http=self._client())
        else:
            result = await check(target, root, http=self._client())
        return {**result.model_dump(mode="json"), "kind": target.kind}

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
