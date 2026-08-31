from __future__ import annotations

import threading
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core import metrics
from app.core.httpcache import route_label
from app.core.logging import get_logger, new_request_id, request_id
from app.core.ratelimit import client_identity, limiter, rule_for

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

_QUIET_PATHS = frozenset({"/api/health", "/openapi.json", "/docs", "/redoc", "/"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        token = request_id.set(incoming[:64] or new_request_id())
        started = time.perf_counter()

        metrics.http_in_flight.inc()

        try:
            response = await call_next(request)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if request.url.path not in _QUIET_PATHS:
                logger.info(
                    "%s %s -> %d in %.0fms",
                    request.method,
                    request.url.path,
                    response.status_code,
                    elapsed_ms,
                )

            self._measure(request, elapsed_ms, str(response.status_code // 100) + "xx")
            response.headers[REQUEST_ID_HEADER] = request_id.get()
            return response
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            logger.exception(
                "%s %s failed in %.0fms",
                request.method,
                request.url.path,
                elapsed_ms,
            )
            # An exception that escapes here still becomes a 500 further out,
            # so it is counted as one. Leaving it uncounted would make the
            # error rate look best exactly when the failures are worst.
            self._measure(request, elapsed_ms, "5xx")
            raise
        finally:
            metrics.http_in_flight.dec()
            request_id.reset(token)

    @staticmethod
    def _measure(request: Request, elapsed_ms: float, status_class: str) -> None:
        """One request, recorded against its route template.

        The template rather than the URL: see `route_label`. Status is bucketed
        to its class for the same reason — a counter per distinct code buys a
        breakdown nobody reads at the cost of five times the series.
        """
        label = route_label(request)
        metrics.http_requests.inc(route=label, method=request.method, status=status_class)
        metrics.http_request_seconds.observe(
            elapsed_ms / 1000.0, route=label, method=request.method
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Counts first, answers second.

    Ahead of routing on purpose: a request that is over its limit should cost a
    dictionary lookup, not a database round trip and a JSON body. That is also
    why identity here is the client address rather than the account — nothing
    at this point has verified a token, and counting against an unverified
    claim would let anybody reset their own allowance by editing it.

    The RateLimit-* headers go on every answer, not only the refusals. A client
    that can see it has four left can slow down; one that only finds out at
    zero cannot.
    """

    def __init__(self, app: ASGIApp, enabled: bool = True) -> None:
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rule = rule_for(request.method, request.url.path) if self.enabled else None
        if rule is None:
            return await call_next(request)

        identity = client_identity(request.headers, request.client.host if request.client else None)
        allowed, remaining, reset = limiter.check(identity, rule)

        if not allowed:
            logger.warning(
                "rate limited %s %s for %s (%s)",
                request.method,
                request.url.path,
                identity,
                rule.name,
            )
            metrics.rate_limited.inc(rule=rule.name)
            response: Response = JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": (
                            "Too many requests. Wait a moment and try again — this limit is "
                            "here so one busy client cannot slow the platform for everyone."
                        ),
                        "detail": {"retry_after_seconds": reset, "limit": rule.limit},
                        "request_id": request_id.get(),
                    }
                },
            )
            response.headers["Retry-After"] = str(reset)
        else:
            response = await call_next(request)

        response.headers["RateLimit-Limit"] = str(rule.limit)
        response.headers["RateLimit-Remaining"] = str(remaining)
        response.headers["RateLimit-Reset"] = str(reset)
        return response


class CompressExceptStreams:
    """gzip every response except the progress stream.

    The JSON this API returns compresses by roughly three quarters, and the
    hop between a viewer and this box is long enough that the bytes matter
    more than the CPU does.

    The forecast progress endpoint is deliberately left alone. It is
    Server-Sent Events, and its whole contract is that each frame reaches the
    browser as it is produced — a keep-alive comment is fourteen bytes, well
    under any compressor's flush threshold, so gzipping the stream trades the
    liveness it exists for against nothing worth having. This is the same
    reason the CloudFront behaviour for /api/* has compression switched off.
    """

    #: Anything whose path ends here streams and must not be buffered.
    STREAMING_SUFFIX = "/events"

    def __init__(self, app: ASGIApp, minimum_size: int = 512) -> None:
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not scope.get("path", "").endswith(self.STREAMING_SUFFIX):
            await self.compressed(scope, receive, send)
            return
        await self.app(scope, receive, send)


class ConcurrencyLimitMiddleware:
    """Refuse quickly rather than queue forever.

    A rate limit answers "is this client asking for too much?". This answers a
    different question — "is this box already doing as much as it usefully
    can?" — and the two failures it protects against are not the same. One
    abusive client is the limiter's problem. Fifty honest clients arriving at
    once while a forecast has both vCPUs is this one's: every request then
    takes longer than the last, the event loop's queue grows, and the answers
    that eventually come out go to browsers that gave up several minutes ago.
    Work done for a client that has left is the purest waste a server can do.

    So past a ceiling this returns 503 with `Retry-After` immediately. That is
    a worse answer than the right one and a much better answer than a timeout:
    the client learns now, the queue stops growing, and the requests already
    in flight finish at the speed they were going to.

    **Streams do not count.** A progress stream is open for the length of a
    forecast run, so counting it would let a handful of dashboards sitting on
    `/events` consume the whole allowance and shed everything else. They cost
    a socket and a keep-alive every fifteen seconds, not a slot.

    **Health does not count either**, and for a sharper reason: the load
    balancer decides whether this instance is alive by asking it. An instance
    that sheds its own health check under load gets taken out of service at
    exactly the moment the traffic needs somewhere to go.

    Pure ASGI rather than `BaseHTTPMiddleware`, because a shed request should
    cost a comparison and a small response — not the task group, queue and
    two coroutines that the base class allocates before it can decide.
    """

    #: Paths whose in-flight time says nothing about how busy this box is.
    EXEMPT_PREFIXES = ("/api/health", "/docs", "/redoc", "/openapi.json")
    EXEMPT_SUFFIXES = ("/events",)

    #: What a shed client is told to wait. Short on purpose: the condition it
    #: describes is a burst, and a burst is usually over in a second.
    RETRY_AFTER_SECONDS = 2

    def __init__(self, app: ASGIApp, limit: int = 64, enabled: bool = True) -> None:
        if limit < 1:
            raise ValueError("The concurrency ceiling must be at least one request.")
        self.app = app
        self.limit = limit
        self.enabled = enabled
        self._in_flight = 0
        # A single event loop does not need this, and a test that drives the
        # app from a thread pool does. It is uncontended in the normal case.
        self._lock = threading.Lock()

    def _exempt(self, path: str) -> bool:
        return path.startswith(self.EXEMPT_PREFIXES) or path.endswith(self.EXEMPT_SUFFIXES)

    @property
    def in_flight(self) -> int:
        return self._in_flight

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if not self.enabled or scope["type"] != "http" or self._exempt(path):
            await self.app(scope, receive, send)
            return

        with self._lock:
            if self._in_flight >= self.limit:
                admitted = False
            else:
                self._in_flight += 1
                admitted = True

        if not admitted:
            logger.warning(
                "shed %s %s: %d requests already in flight",
                scope.get("method", "?"),
                path,
                self.limit,
            )
            # The raw path, unrouted, would be one series per URL — and a
            # shed request has not been routed, so no template exists yet.
            # The first two segments are bounded and enough to say which part
            # of the API the pressure is on.
            metrics.http_shed.inc(route="/".join(path.split("/")[:3]) or "/")
            response = JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "overloaded",
                        "message": (
                            "The server is at capacity right now. This request was refused "
                            "immediately rather than left to time out — try again in a moment."
                        ),
                        "detail": {
                            "retry_after_seconds": self.RETRY_AFTER_SECONDS,
                            "concurrency_limit": self.limit,
                        },
                        "request_id": request_id.get(),
                    }
                },
                headers={"Retry-After": str(self.RETRY_AFTER_SECONDS)},
            )
            await response(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            with self._lock:
                self._in_flight -= 1
