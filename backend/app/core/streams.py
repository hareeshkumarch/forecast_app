from __future__ import annotations

import contextlib
import json
import time
from collections.abc import AsyncIterator, Iterator

from starlette.requests import Request

from app.core import metrics
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.ratelimit import client_identity

logger = get_logger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

KEEPALIVE = b": keep-alive\n\n"


class TooManyStreamsError(AppError):
    status_code = 429
    code = "too_many_streams"


streams_open = metrics.registry.gauge(
    "forecasting_sse_streams_open",
    "Server-Sent Events connections currently held open, by endpoint.",
    ("kind",),
)

streams_refused = metrics.registry.counter(
    "forecasting_sse_streams_refused_total",
    "Stream connections refused, by endpoint and by which ceiling refused them.",
    ("kind", "reason"),
)


class Lease:
    __slots__ = ("_registry", "_released", "identity", "kind")

    def __init__(self, registry: StreamRegistry, identity: str, kind: str) -> None:
        self._registry = registry
        self.identity = identity
        self.kind = kind
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._registry._release(self)


class StreamRegistry:
    def __init__(self) -> None:
        self._per_client: dict[str, int] = {}
        self._total = 0

    @property
    def total(self) -> int:
        return self._total

    def for_client(self, identity: str) -> int:
        return self._per_client.get(identity, 0)

    def acquire(self, identity: str, kind: str) -> Lease:
        per_client = settings.sse_max_streams_per_client
        total = settings.sse_max_streams_total

        if self._total >= total:
            streams_refused.inc(kind=kind, reason="process")
            logger.warning("Refused a %s stream: %d already open on this process.", kind, total)
            raise TooManyStreamsError(
                "This server is holding as many live connections as it can. The page will "
                "keep working — it falls back to asking for updates instead of being told.",
                detail={"retry_after_seconds": settings.sse_retry_after_seconds, "limit": total},
                headers={"Retry-After": str(settings.sse_retry_after_seconds)},
            )

        if self._per_client.get(identity, 0) >= per_client:
            streams_refused.inc(kind=kind, reason="client")
            logger.warning(
                "Refused a %s stream for %s: %d already open.", kind, identity, per_client
            )
            raise TooManyStreamsError(
                "Too many live connections are open for this account. Close a tab you are not "
                "using, or wait a moment — updates keep arriving either way.",
                detail={
                    "retry_after_seconds": settings.sse_retry_after_seconds,
                    "limit": per_client,
                },
                headers={"Retry-After": str(settings.sse_retry_after_seconds)},
            )

        self._per_client[identity] = self._per_client.get(identity, 0) + 1
        self._total += 1
        streams_open.inc(kind=kind)
        return Lease(self, identity, kind)

    def _release(self, lease: Lease) -> None:
        remaining = self._per_client.get(lease.identity, 0) - 1
        if remaining > 0:
            self._per_client[lease.identity] = remaining
        else:
            self._per_client.pop(lease.identity, None)
        self._total = max(0, self._total - 1)
        streams_open.dec(kind=lease.kind)

    def forget_all(self) -> None:
        self._per_client.clear()
        self._total = 0


registry = StreamRegistry()


def identify(request: Request, user_id: str | None) -> str:
    if user_id:
        return f"user:{user_id}"
    host = request.client.host if request.client else None
    return f"ip:{client_identity(request.headers, host)}"


@contextlib.contextmanager
def leased(request: Request, user_id: str | None, kind: str) -> Iterator[Lease]:
    lease = registry.acquire(identify(request, user_id), kind)
    try:
        yield lease
    except BaseException:
        lease.release()
        raise


def frame(data: str = "{}", *, event: str | None = None, event_id: str | None = None) -> bytes:
    parts: list[str] = []
    if event_id:
        parts.append(f"id: {event_id}")
    if event:
        parts.append(f"event: {event}")
    parts.extend(f"data: {line}" for line in data.split("\n"))
    return ("\n".join(parts) + "\n\n").encode()


def json_frame(payload: dict, *, event: str | None = None, event_id: str | None = None) -> bytes:
    return frame(json.dumps(payload, separators=(",", ":")), event=event, event_id=event_id)


def preamble() -> bytes:
    return f"retry: {settings.sse_retry_hint_ms}\n\n".encode()


class Deadline:
    __slots__ = ("_expires_at",)

    def __init__(self, seconds: float | None = None) -> None:
        limit = settings.sse_max_lifetime_seconds if seconds is None else seconds
        self._expires_at = time.monotonic() + limit

    @property
    def passed(self) -> bool:
        return time.monotonic() >= self._expires_at

    @property
    def remaining(self) -> float:
        return max(0.0, self._expires_at - time.monotonic())


EXPIRED = frame('{"reason":"lifetime"}', event="expired")


async def released_after(source: AsyncIterator[bytes], lease: Lease) -> AsyncIterator[bytes]:
    try:
        async for chunk in source:
            yield chunk
    finally:
        lease.release()
