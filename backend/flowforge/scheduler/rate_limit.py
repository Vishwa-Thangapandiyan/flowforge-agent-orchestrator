"""Async token bucket (D5, D8). Owner: Person B."""

from __future__ import annotations

import asyncio


class TokenBucket:
    """`rate_per_min` tokens refill continuously; bursts up to `capacity`.

    acquire() waits with asyncio.sleep (never busy-loops) until a token is available.
    Waiters queue on a lock while sleeping, so tokens are handed out first-come first-served.
    """

    def __init__(self, rate_per_min: float, capacity: int | None = None):
        if rate_per_min <= 0:
            raise ValueError("rate_per_min must be positive")
        self.rate_per_s = rate_per_min / 60
        self.capacity = capacity if capacity is not None else max(1, int(rate_per_min / 6))
        self.tokens = float(self.capacity)
        self._last: float | None = None
        self._lock = asyncio.Lock()

    def _refill(self, now: float) -> None:
        if self._last is not None:
            self.tokens = min(self.capacity, self.tokens + (now - self._last) * self.rate_per_s)
        self._last = now

    async def acquire(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            self._refill(loop.time())
            while self.tokens < 1:
                await asyncio.sleep((1 - self.tokens) / self.rate_per_s)
                self._refill(loop.time())
            self.tokens -= 1
