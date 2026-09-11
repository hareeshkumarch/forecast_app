from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date, datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import Response

from app.core import metrics
from app.core.config import settings

APP_REVISION = settings.app_version

CACHE_CONTROL = "private, no-cache"

_TOKEN_LENGTH = 16


def _part(value: object) -> str:
    if value is None:
        return "~"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date | UUID):
        return str(value)
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, dict):
        return "{" + ",".join(f"{k}={_part(v)}" for k, v in sorted(value.items())) + "}"
    if isinstance(value, list | tuple | set | frozenset):
        rendered = [_part(item) for item in value]
        if isinstance(value, set | frozenset):
            rendered.sort()
        return "[" + ",".join(rendered) + "]"
    return str(value)


def version_token(*parts: Any) -> str:
    joined = "\x1f".join(_part(part) for part in parts)
    return hashlib.blake2b(joined.encode("utf-8"), digest_size=_TOKEN_LENGTH // 2).hexdigest()


def etag_for(token: str) -> str:
    return f'W/"{token}"'


def _candidates(header: str) -> Iterable[str]:
    for raw in header.split(","):
        candidate = raw.strip()
        if candidate:
            yield candidate


def matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False

    wanted = etag.removeprefix("W/")
    for candidate in _candidates(if_none_match):
        if candidate == "*" or candidate.removeprefix("W/") == wanted:
            return True
    return False


def not_modified(etag: str) -> Response:
    return Response(
        status_code=304,
        headers={"ETag": etag, "Cache-Control": CACHE_CONTROL},
    )


def apply(response: Response, etag: str) -> None:
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = CACHE_CONTROL


def route_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else request.url.path


OPENAPI_RESPONSES: dict[int | str, dict[str, Any]] = {
    304: {
        "description": (
            "The client's `If-None-Match` matched the current version. No body is sent and "
            "no aggregates are computed; reuse the copy you already hold."
        )
    }
}


@lru_cache(maxsize=64)
def shape_token(model: type[BaseModel]) -> str:
    schema = json.dumps(model.model_json_schema(), sort_keys=True, default=str)
    return hashlib.blake2b(schema.encode("utf-8"), digest_size=4).hexdigest()


def conditional(request: Request, response: Response, token: str) -> Response | None:
    etag = etag_for(token)
    label = route_label(request)

    if matches(request.headers.get("if-none-match"), etag):
        metrics.conditional_responses.inc(route=label, outcome="not_modified")
        return not_modified(etag)

    metrics.conditional_responses.inc(route=label, outcome="rendered")
    apply(response, etag)
    return None
