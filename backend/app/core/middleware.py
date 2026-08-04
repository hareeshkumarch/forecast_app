from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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
        finally:
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
        request_id.reset(token)
        return response
