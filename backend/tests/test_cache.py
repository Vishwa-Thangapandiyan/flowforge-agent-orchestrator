import asyncio

import pytest

from flowforge.scheduler.cache import CallCache, cache_key
from flowforge.storage import Storage


def test_key_ignores_dict_order_but_not_type():
    assert cache_key("http", {"a": 1, "b": 2}) == cache_key("http", {"b": 2, "a": 1})
    assert cache_key("http", {"a": 1}) != cache_key("llm", {"a": 1})


async def test_single_flight_collapses_concurrent_calls():
    cache, calls = CallCache(), 0

    async def fn():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return "v"

    results = await asyncio.gather(*(cache.get_or_run("k", fn, persistent=False) for _ in range(5)))
    assert calls == 1
    assert [v for v, _ in results] == ["v"] * 5
    assert sorted(hit for _, hit in results) == [False, True, True, True, True]
    assert (cache.hits, cache.misses) == (4, 1)


async def test_failures_are_shared_but_not_cached():
    cache, calls = CallCache(), 0

    async def boom():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        raise RuntimeError("x")

    results = await asyncio.gather(
        cache.get_or_run("k", boom, False), cache.get_or_run("k", boom, False), return_exceptions=True
    )
    assert all(isinstance(r, RuntimeError) for r in results) and calls == 1
    with pytest.raises(RuntimeError):
        await cache.get_or_run("k", boom, False)
    assert calls == 2  # retried, not served from cache


async def test_persistent_layer(tmp_path):
    db = Storage(tmp_path / "c.db")

    async def fn():
        return {"n": 1}

    await CallCache(db).get_or_run("k", fn, persistent=True)
    value, hit = await CallCache(db).get_or_run("k", fn, persistent=True)  # fresh run, same db
    assert (value, hit) == ({"n": 1}, True)
    _, hit = await CallCache(db).get_or_run("other", fn, persistent=False)
    assert not hit and db.get_cached("other") == (False, None)
