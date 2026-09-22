"""Plain HTTP call via httpx (D9). Owner: Person C.

params: method (default GET), url, headers?, json?, max_chars? (truncate body; default 20000)
output: {"status": int, "body": str | parsed JSON}

429 / 5xx / timeouts / connection errors → TransientNodeError (honour Retry-After);
other 4xx → NodeError.
"""

from __future__ import annotations

from typing import Any

from flowforge.nodes.base import Node


class HTTPNode(Node):
    type = "http"

    def cacheable_across_runs(self, params: dict[str, Any]) -> bool:
        return params.get("method", "GET").upper() == "GET"

    async def run(self, params: dict[str, Any]) -> Any:
        raise NotImplementedError
