from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar

from app.core.config import settings

request_id: ContextVar[str] = ContextVar("request_id", default="-")

_CONFIGURED = False

_NOISY_LOGGERS = {
    "sqlalchemy.engine": logging.WARNING,
    "asyncio": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "cmdstanpy": logging.ERROR,
    "prophet": logging.WARNING,
}

_TEXT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] | %(message)s"


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(
        _JsonFormatter()
        if settings.log_format == "json"
        else logging.Formatter(_TEXT_FORMAT, "%H:%M:%S")
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    for name, level in _NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(level)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
