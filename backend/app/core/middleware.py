from __future__ import annotations

import threading
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
            self._measure(request, elapsed_ms, "5xx")
            raise
        finally:
            metrics.http_in_flight.dec()
            request_id.reset(token)

    @staticmethod
    def _measure(request: Request, elapsed_ms: float, status_class: str) -> None:
        label = route_label(request)
        metrics.http_requests.inc(route=label, method=request.method, status=status_class)
        metrics.http_request_seconds.observe(
            elapsed_ms / 1000.0, route=label, method=request.method
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
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
    EXEMPT_PREFIXES = ("/api/health", "/docs", "/redoc", "/openapi.json")
    EXEMPT_SUFFIXES = ("/events",)

    RETRY_AFTER_SECONDS = 2

    def __init__(self, app: ASGIApp, limit: int = 64, enabled: bool = True) -> None:
        if limit < 1:
            raise ValueError("The concurrency ceiling must be at least one request.")
        self.app = app
        self.limit = limit
        self.enabled = enabled
        self._in_flight = 0
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


class SecurityHeaders:
    HEADERS = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-opener-policy", b"same-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    )

    HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        secure = scope.get("scheme") == "https" or _forwarded_https(scope)

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {name.lower() for name, _ in headers}
                for name, value in self.HEADERS:
                    if name not in present:
                        headers.append((name, value))
                if secure and self.HSTS[0] not in present:
                    headers.append(self.HSTS)
            await send(message)

        await self.app(scope, receive, with_headers)


def _forwarded_https(scope: Scope) -> bool:
    for name, value in scope.get("headers", ()):
        if name == b"x-forwarded-proto":
            return value.decode("latin-1").split(",")[0].strip().lower() == "https"
    return False
