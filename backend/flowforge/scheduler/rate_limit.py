"""Async token bucket (D5, D8). Owner: Person B."""

from __future__ import annotations


class TokenBucket:
    """`rate_per_min` tokens refill continuously; bursts up to `capacity`.

    acquire() waits (asyncio.sleep, never busy-loops) until a token is available.
    Must be fair under contention — use an asyncio.Lock around the refill+take.
    """

    def __init__(self, rate_per_min: float, capacity: int | None = None):
        self.rate_per_s = rate_per_min / 60
        self.capacity = capacity if capacity is not None else max(1, int(rate_per_min / 6))

    async def acquire(self) -> None:
        raise NotImplementedError
