"""Call dedupe: single-flight in-run memo + safe persistent cache (D3). Owner: Person B."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any


def cache_key(step_type: str, resolved_params: dict[str, Any]) -> str:
    canonical = json.dumps(resolved_params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{step_type}\x00{canonical}".encode()).hexdigest()


class CallCache:
    """One instance per run.

    get_or_run(key, fn, persistent):
      1. finished result in memo           → return it (hit)
      2. same key currently in flight      → await the same asyncio.Future (hit, single-flight)
      3. persistent and in storage         → return stored (hit)
      4. otherwise run fn(), store the result (memo, and storage if persistent)
    Failures must NOT be cached; waiters on a failed future see the exception.
    Track hits/misses for the benchmark.
    """

    def __init__(self, storage: Any | None = None):
        self.storage = storage
        self.hits = 0
        self.misses = 0

    async def get_or_run(self, key: str, fn: Callable[[], Awaitable[Any]], persistent: bool) -> Any:
        raise NotImplementedError
