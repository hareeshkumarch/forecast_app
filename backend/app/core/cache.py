"""A read-through cache whose keys carry the version of what they hold.

The dashboard is six endpoints over one run, and a person looking at it
switches scenario, drags a date range and picks a breakdown column — each of
which re-runs a fan of aggregate queries over the same immutable rows. The
answers are pure functions of a finished run, so computing them twice is work
nobody asked for.

**Version-keyed, not invalidated.** The interesting decision here is that a
key contains a token derived from the row's own `updated_at` (see
`app/core/httpcache.py`). Anything that changes the underlying data changes
the token, which changes the key, which misses. An entry can therefore never
be served stale — the worst it can be is garbage, and garbage ages out on TTL
and LRU. That is the difference between a cache that needs every writer in the
codebase to remember to call `invalidate()` and one that is correct because of
its shape. Tags are still here, and `invalidate_tag` still works, but they are
for reclaiming space promptly (a deleted run), not for correctness.

**Single-flight.** Ten browser tabs opening the same dashboard at once used to
be ten identical query fans. Concurrent misses on one key now await the first
one's result. This is where a cache actually earns its keep on a small box:
the load it sheds is the correlated load, which is the load that hurts.

**Bounded, and honest about the loop.** Entries are capped and evicted least
recently used, because an unbounded map keyed by run id and date range is a
memory leak with a public trigger. In-flight futures are tagged with the event
loop that created them: the test suite gives every test its own loop, and
awaiting a future from a loop that has closed raises somewhere unhelpful. A
future from another loop is ignored and the value recomputed, which costs a
duplicate computation in the one case where correctness is otherwise at risk.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from app.core import metrics
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

#: Long enough that a person clicking around the dashboard stays inside one
#: entry, short enough that a key which will never be asked for again is not
#: holding memory into the next hour. Correctness does not depend on it —
#: version-keyed entries are never stale — so this is purely a memory knob.
DEFAULT_TTL_SECONDS = 300.0

#: Roughly a hundred runs' worth of dashboards at six views each. The values
#: are assembled Pydantic models of a few kilobytes, so this is single-digit
#: megabytes at the ceiling on a box where the forecast pool wants the rest.
DEFAULT_MAX_ENTRIES = 600


@dataclass(slots=True)
class _Entry:
    value: Any
    expires_at: float
    tags: frozenset[str] = field(default_factory=frozenset)


@dataclass(slots=True)
class _Pending:
    """A computation in flight, and the loop it belongs to."""

    future: asyncio.Future[Any]
    loop: asyncio.AbstractEventLoop


@dataclass(frozen=True, slots=True)
class CacheStats:
    hits: int
    misses: int
    coalesced: int
    evictions: int
    entries: int

    @property
    def hit_ratio(self) -> float:
        served = self.hits + self.misses + self.coalesced
        return round(self.hits / served, 4) if served else 0.0


class AsyncCache(Generic[T]):
    """TTL + LRU, with single-flight and tag-based reclamation."""

    def __init__(
        self,
        name: str,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("A cache TTL must be positive.")
        if max_entries < 1:
            raise ValueError("A cache must be allowed at least one entry.")
        self.name = name
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._pending: dict[str, _Pending] = {}
        self._hits = 0
        self._misses = 0
        self._coalesced = 0
        self._evictions = 0

    # ---- reading ---------------------------------------------------------

    def peek(self, key: str, *, now: float | None = None) -> T | None:
        """The value if it is present and live. Does not count as a hit.

        For tests and for the code paths that want to know whether a value is
        already there without changing the statistics they are about to read.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= (time.monotonic() if now is None else now):
            self._entries.pop(key, None)
            return None
        return entry.value  # type: ignore[no-any-return]

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[T]],
        *,
        ttl_seconds: float | None = None,
        tags: Iterable[str] = (),
    ) -> T:
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry is not None and entry.expires_at > now:
            self._entries.move_to_end(key)
            self._hits += 1
            metrics.cache_events.inc(cache=self.name, outcome="hit")
            return entry.value  # type: ignore[no-any-return]
        if entry is not None:
            self._entries.pop(key, None)

        loop = asyncio.get_running_loop()
        pending = self._pending.get(key)
        if pending is not None and pending.loop is loop and not pending.future.done():
            self._coalesced += 1
            metrics.cache_events.inc(cache=self.name, outcome="coalesced")
            return await asyncio.shield(pending.future)  # type: ignore[no-any-return]

        self._misses += 1
        metrics.cache_events.inc(cache=self.name, outcome="miss")

        future: asyncio.Future[T] = loop.create_future()
        self._pending[key] = _Pending(future=future, loop=loop)
        try:
            value = await factory()
        except BaseException as exc:
            # Everybody waiting on this key learns the computation failed
            # rather than hanging until their own timeout. Nothing is stored:
            # a failure is not an answer, and caching one would keep a
            # transient database error alive for the whole TTL.
            if not future.done():
                future.set_exception(exc)
            # Retrieving it here means a future nobody happened to await
            # cannot surface later as the loop's "exception was never
            # retrieved" warning, which arrives with no stack anybody can use.
            if future.done() and not future.cancelled():
                future.exception()
            raise
        else:
            if not future.done():
                future.set_result(value)
            self._store(key, value, ttl_seconds or self.ttl_seconds, frozenset(tags))
            return value
        finally:
            if self._pending.get(key) is not None and self._pending[key].future is future:
                del self._pending[key]

    # ---- writing and reclaiming -----------------------------------------

    def _store(self, key: str, value: T, ttl: float, tags: frozenset[str]) -> None:
        self._entries[key] = _Entry(value=value, expires_at=time.monotonic() + ttl, tags=tags)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
            self._evictions += 1
            metrics.cache_events.inc(cache=self.name, outcome="evicted")
        metrics.cache_entries.set(len(self._entries), cache=self.name)

    def invalidate_key(self, key: str) -> bool:
        return self._entries.pop(key, None) is not None

    def invalidate_tag(self, tag: str) -> int:
        """Drop everything carrying this tag. Reclamation, not correctness.

        Called when a run is deleted or rewritten, so its entries stop holding
        memory immediately rather than at their TTL. A caller that forgets is
        not serving anything wrong — the version in the key already saw to
        that — it is only holding a few kilobytes for five minutes longer.
        """
        doomed = [key for key, entry in self._entries.items() if tag in entry.tags]
        for key in doomed:
            del self._entries[key]
        if doomed:
            metrics.cache_entries.set(len(self._entries), cache=self.name)
            logger.debug("cache %s dropped %d entries for %s", self.name, len(doomed), tag)
        return len(doomed)

    def clear(self) -> None:
        self._entries.clear()
        self._pending.clear()
        metrics.cache_entries.set(0, cache=self.name)

    def reset_stats(self) -> None:
        self._hits = self._misses = self._coalesced = self._evictions = 0

    @property
    def stats(self) -> CacheStats:
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            coalesced=self._coalesced,
            evictions=self._evictions,
            entries=len(self._entries),
        )


#: The dashboard's aggregates. One cache rather than one per endpoint: the
#: endpoint name is already the first component of every key, and a single LRU
#: lets a run somebody is actually looking at keep its entries while a run
#: nobody has opened since this morning loses its.
dashboard_cache: AsyncCache[Any] = AsyncCache("dashboard")

#: Every cache in the process, so a test can reset them and the health
#: endpoint can report them without either having to know the list.
CACHES: tuple[AsyncCache[Any], ...] = (dashboard_cache,)


def clear_all() -> None:
    for cache in CACHES:
        cache.clear()
        cache.reset_stats()


def run_tag(run_id: uuid.UUID) -> str:
    """The tag every cached answer derived from one forecast run carries."""
    return f"run:{run_id}"


def forget_run(run_id: uuid.UUID) -> int:
    """Drop this run's cached answers. Reclamation, not correctness.

    Called where a run is deleted or its insights are rewritten. A caller that
    forgets is not serving anything wrong — the version inside every key
    already saw to that — it is only holding a few kilobytes until the TTL.
    That is deliberate: an invalidation anybody can forget is a bug waiting
    for a deadline, and this design makes forgetting cost memory rather than
    correctness.

    Lives here rather than beside the dashboard routes so that the services
    which delete and rewrite runs can call it without importing a router.
    """
    return dashboard_cache.invalidate_tag(run_tag(run_id))
