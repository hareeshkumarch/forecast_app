from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.logging import get_logger, new_request_id, request_id

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
            raise
        finally:
            request_id.reset(token)


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
