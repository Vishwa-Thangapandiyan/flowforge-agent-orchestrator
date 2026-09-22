"""Sleep-based node for tests and the simulated benchmark track (D6). Never touches the network.

params:
  duration_ms: how long to "work"
  output:      value to return (default: {"step_done": true})
  fail:        "transient" | "permanent" to simulate errors
  fail_times:  how many calls fail before succeeding (default: always)
"""

from __future__ import annotations

import asyncio
from typing import Any

from flowforge.nodes.base import Node, NodeError, TransientNodeError


class MockNode(Node):
    type = "mock"

    def __init__(self) -> None:
        self.calls = 0
        self._failures: dict[str, int] = {}

    async def run(self, params: dict[str, Any]) -> Any:
        self.calls += 1
        await asyncio.sleep(params.get("duration_ms", 100) / 1000)

        fail = params.get("fail")
        if fail:
            key = repr(sorted(params.items()))
            done = self._failures.get(key, 0)
            limit = params.get("fail_times")
            if limit is None or done < limit:
                self._failures[key] = done + 1
                if fail == "transient":
                    raise TransientNodeError("simulated transient failure")
                raise NodeError("simulated permanent failure")

        return params.get("output", {"step_done": True})
