from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.logging import get_logger, request_id

logger = get_logger(__name__)


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str, *, detail: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class UnsupportedFileError(AppError):
    status_code = 415
    code = "unsupported_file"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class ConnectorError(AppError):
    status_code = 400
    code = "connector_error"


class ForecastError(AppError):
    status_code = 400
    code = "forecast_error"


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorised",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_file",
    422: "validation_error",
    429: "rate_limited",
}


def _response(status_code: int, code: str, message: str, detail: dict[str, object]) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "detail": detail,
                "request_id": request_id.get(),
            }
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.info("%s on %s %s: %s", exc.code, request.method, request.url.path, exc.message)
        return _response(exc.status_code, exc.code, exc.message, exc.detail)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        message = str(exc.detail) if exc.detail else "The request could not be completed."
        logger.info("%s on %s %s", code, request.method, request.url.path)
        return _response(exc.status_code, code, message, {})

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "type": str(error.get("type", "value_error")),
                "msg": str(error.get("msg", "")),
            }
            for error in exc.errors()
        ]
        logger.info(
            "validation_error on %s %s: %d problem(s)",
            request.method,
            request.url.path,
            len(errors),
        )
        return _response(
            422,
            "validation_error",
            "The request could not be accepted. Check the highlighted fields.",
            {"errors": errors},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path
        )
        return _response(
            500,
            "internal_error",
            "Something went wrong on our side. Try again, and quote the request id if it persists.",
            {},
        )
