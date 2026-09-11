from __future__ import annotations

import asyncio

import pytest

from app.core.cache import AsyncCache, dashboard_cache, forget_run, run_tag


async def test_a_second_read_is_served_without_recomputing() -> None:
    cache: AsyncCache[str] = AsyncCache("t")
    calls = 0

    async def compute() -> str:
        nonlocal calls
        calls += 1
        return "value"

    assert await cache.get_or_set("k", compute) == "value"
    assert await cache.get_or_set("k", compute) == "value"
    assert calls == 1
    assert cache.stats.hits == 1


async def test_concurrent_misses_wait_on_one_computation() -> None:
    cache: AsyncCache[str] = AsyncCache("t")
    calls = 0

    async def slow() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return "value"

    results = await asyncio.gather(*(cache.get_or_set("k", slow) for _ in range(10)))

    assert results == ["value"] * 10
    assert calls == 1
    assert cache.stats.coalesced == 9


async def test_a_failure_reaches_every_waiter_and_is_not_stored() -> None:
    cache: AsyncCache[str] = AsyncCache("t")

    async def boom() -> str:
        await asyncio.sleep(0.01)
        raise RuntimeError("the database said no")

    outcomes = await asyncio.gather(
        *(cache.get_or_set("k", boom) for _ in range(3)), return_exceptions=True
    )

    assert all(isinstance(outcome, RuntimeError) for outcome in outcomes)
    assert cache.stats.entries == 0
    assert cache.peek("k") is None


async def test_an_entry_expires() -> None:
    cache: AsyncCache[str] = AsyncCache("t", ttl_seconds=0.05)
    calls = 0

    async def compute() -> str:
        nonlocal calls
        calls += 1
        return "value"

    await cache.get_or_set("k", compute)
    await asyncio.sleep(0.08)
    await cache.get_or_set("k", compute)

    assert calls == 2


async def test_the_least_recently_used_entry_is_dropped_first() -> None:
    cache: AsyncCache[str] = AsyncCache("t", max_entries=2)

    async def value(name: str) -> str:
        return name

    await cache.get_or_set("a", lambda: value("a"))
    await cache.get_or_set("b", lambda: value("b"))
    await cache.get_or_set("a", lambda: value("a"))
    await cache.get_or_set("c", lambda: value("c"))

    assert cache.peek("a") == "a"
    assert cache.peek("c") == "c"
    assert cache.peek("b") is None
    assert cache.stats.evictions == 1


async def test_a_tag_reclaims_every_entry_it_covers() -> None:
    cache: AsyncCache[str] = AsyncCache("t")

    async def value(name: str) -> str:
        return name

    await cache.get_or_set("summary", lambda: value("s"), tags=("run:1",))
    await cache.get_or_set("drivers", lambda: value("d"), tags=("run:1",))
    await cache.get_or_set("other", lambda: value("o"), tags=("run:2",))

    assert cache.invalidate_tag("run:1") == 2
    assert cache.peek("other") == "o"
    assert cache.stats.entries == 1


async def test_forgetting_a_run_drops_only_that_run_s_entries() -> None:
    import uuid

    kept, doomed = uuid.uuid4(), uuid.uuid4()

    async def value() -> str:
        return "x"

    await dashboard_cache.get_or_set("a", value, tags=(run_tag(doomed),))
    await dashboard_cache.get_or_set("b", value, tags=(run_tag(kept),))

    assert forget_run(doomed) == 1
    assert dashboard_cache.peek("b") == "x"


async def test_a_hit_ratio_is_reported_over_everything_served() -> None:
    cache: AsyncCache[str] = AsyncCache("t")

    async def value() -> str:
        return "x"

    await cache.get_or_set("k", value)
    await cache.get_or_set("k", value)
    await cache.get_or_set("k", value)

    assert cache.stats.hit_ratio == pytest.approx(2 / 3, abs=1e-4)


def test_a_pending_computation_from_a_dead_loop_is_not_awaited() -> None:
    from app.core.cache import _Pending

    cache: AsyncCache[str] = AsyncCache("t")

    async def strand_a_future() -> None:
        loop = asyncio.get_running_loop()
        cache._pending["k"] = _Pending(future=loop.create_future(), loop=loop)

    asyncio.run(strand_a_future())

    async def read_on_a_new_loop() -> str:
        async def value() -> str:
            return "computed here"

        return await cache.get_or_set("k", value)

    assert asyncio.run(read_on_a_new_loop()) == "computed here"


def test_a_cache_refuses_a_configuration_that_cannot_hold_anything() -> None:
    with pytest.raises(ValueError, match="TTL must be positive"):
        AsyncCache("t", ttl_seconds=0)
    with pytest.raises(ValueError, match="at least one entry"):
        AsyncCache("t", max_entries=0)


async def test_a_waiter_survives_the_leader_closing_their_tab() -> None:
    cache: AsyncCache[str] = AsyncCache("t")
    started = asyncio.Event()
    calls = 0

    async def slow() -> str:
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.sleep(0.2)
        return "value"

    leader = asyncio.create_task(cache.get_or_set("k", slow))
    await started.wait()
    waiter = asyncio.create_task(cache.get_or_set("k", slow))
    await asyncio.sleep(0.02)

    leader.cancel()

    assert await waiter == "value"
    assert calls == 2


async def test_a_waiter_that_is_itself_cancelled_still_stops() -> None:
    cache: AsyncCache[str] = AsyncCache("t")
    started = asyncio.Event()

    async def slow() -> str:
        started.set()
        await asyncio.sleep(5)
        return "value"

    leader = asyncio.create_task(cache.get_or_set("k", slow))
    await started.wait()
    waiter = asyncio.create_task(cache.get_or_set("k", slow))
    await asyncio.sleep(0.02)

    waiter.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert leader.done() is False

    leader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader
