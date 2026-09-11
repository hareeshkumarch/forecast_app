from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Final, Generic, TypeVar

from app.core import metrics
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

DEFAULT_TTL_SECONDS = 300.0

DEFAULT_MAX_ENTRIES = 600


@dataclass(slots=True)
class _Entry:
    value: Any
    expires_at: float
    tags: frozenset[str] = field(default_factory=frozenset)


_ABANDONED: Final = object()


@dataclass(slots=True)
class _Pending:
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

    def peek(self, key: str, *, now: float | None = None) -> T | None:
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
            joined = await self._join(pending)
            if joined is not _ABANDONED:
                return joined  # type: ignore[no-any-return]

        self._misses += 1
        metrics.cache_events.inc(cache=self.name, outcome="miss")

        future: asyncio.Future[T] = loop.create_future()
        self._pending[key] = _Pending(future=future, loop=loop)
        try:
            value = await factory()
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
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

    async def _join(self, pending: _Pending) -> Any:
        try:
            return await asyncio.shield(pending.future)
        except asyncio.CancelledError:
            leader_gone = pending.future.cancelled() or (
                pending.future.done()
                and isinstance(pending.future.exception(), asyncio.CancelledError)
            )
            if not leader_gone:
                raise
            return _ABANDONED

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


dashboard_cache: AsyncCache[Any] = AsyncCache("dashboard")

CACHES: tuple[AsyncCache[Any], ...] = (dashboard_cache,)


def clear_all() -> None:
    for cache in CACHES:
        cache.clear()
        cache.reset_stats()


def run_tag(run_id: uuid.UUID) -> str:
    return f"run:{run_id}"


def forget_run(run_id: uuid.UUID) -> int:
    return dashboard_cache.invalidate_tag(run_tag(run_id))
