import asyncio

import pytest

from flowforge.scheduler.rate_limit import TokenBucket


async def test_burst_then_throttle():
    bucket = TokenBucket(rate_per_min=600, capacity=2)  # 10 tokens/s
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    for _ in range(4):
        await bucket.acquire()
    elapsed = loop.time() - t0
    # 2 free from the burst, then 2 more at 0.1 s each
    assert 0.18 <= elapsed < 0.4


async def test_concurrent_acquirers_are_all_served():
    bucket = TokenBucket(rate_per_min=1200, capacity=1)
    await asyncio.gather(*(bucket.acquire() for _ in range(5)))
    assert bucket.tokens < 1


def test_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        TokenBucket(0)
