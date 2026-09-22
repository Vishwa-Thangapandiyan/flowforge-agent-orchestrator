"""Call dedupe: single-flight in-run memo + safe persistent cache (D3). Owner: Person B."""

from __future__ import annotations

import asyncio
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
    Failures are NOT cached; waiters on a failed call see the same exception.
    """

    def __init__(self, storage: Any | None = None):
        self.storage = storage
        self.hits = 0
        self.misses = 0
        self._done: dict[str, Any] = {}
        self._inflight: dict[str, asyncio.Future[Any]] = {}

    def has(self, key: str) -> bool:
        """True if a call for `key` is finished or running — awaiting it needs no worker slot."""
        return key in self._done or key in self._inflight

    async def get_or_run(
        self, key: str, fn: Callable[[], Awaitable[Any]], persistent: bool
    ) -> tuple[Any, bool]:
        """Returns (value, cache_hit)."""
        if key in self._done:
            self.hits += 1
            return self._done[key], True
        if key in self._inflight:
            self.hits += 1
            # shield: one waiter being cancelled must not cancel the shared call
            return await asyncio.shield(self._inflight[key]), True
        if persistent and self.storage is not None:
            found, value = self.storage.get_cached(key)
            if found:
                self.hits += 1
                self._done[key] = value
                return value, True

        self.misses += 1
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value = await fn()
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                future.cancel()
            else:
                future.set_exception(exc)
                future.exception()  # mark retrieved: no "never retrieved" warning if nobody waits
            raise
        finally:
            del self._inflight[key]

        self._done[key] = value
        future.set_result(value)
        if persistent and self.storage is not None:
            self.storage.put_cached(key, value)
        return value, False
