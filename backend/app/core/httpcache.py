"""Conditional GETs: answer "nothing has changed" without computing anything.

A dashboard page fires six aggregate queries per view, and the person driving
it flips between base, best and worst and back again. Every one of those flips
recomputed a number that had not moved, serialised it, gzipped it and sent it
down a link to a browser that already held an identical copy.

The shape of the fix is the oldest one in HTTP. Each read endpoint derives a
short **version token** from the state its answer depends on — the run's
`updated_at`, its scored timestamp, the query that selected it — and offers
that as an `ETag`. A browser that already has the answer sends it back in
`If-None-Match`, and the handler returns `304 Not Modified` *before* running
the aggregates. The saving is the query fan, not just the bytes.

Three decisions worth stating:

**Weak validators.** These are `W/"..."`. A strong ETag promises byte equality
for a given representation, and this app gzips through a middleware that runs
after the handler, so the same token can end up on gzipped and plain bodies —
which a strong validator would be lying about. Weak promises semantic
equality, which is exactly what a version token can honestly offer, and every
cache treats it as sufficient for `If-None-Match`.

**`no-cache`, not `max-age`.** `no-cache` does not mean "do not store": it
means "store it, but ask before using it". That is precisely the contract
here. A `max-age` of even fifteen seconds would let a browser show a figure
from before somebody rewrote the insights, and the whole point of deriving the
token from the data is that nobody ever sees a stale number. Revalidation
costs one 304, which is a few hundred bytes and no database work.

**`private`.** These answers are behind sign-in and CloudFront sits in front
of `/api/*`. `private` keeps a shared cache from holding one account's answer
and handing it to the next person.

The same token keys the read-through cache in `app/core/cache.py`, so the two
mechanisms cannot disagree about what version they are talking about.
"""

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

#: Mixed into every version token, so a release invalidates every client's
#: stored copy exactly once. `shape_token` catches a changed response shape on
#: its own; this catches the other kind of change — same shape, different
#: number — which no automatic signal can see.
#:
#: Read from the settings rather than written here, so it is the same string
#: the API advertises as its version and there is one place to bump. A
#: deployment that sets APP_VERSION to its build id gets a clean invalidation
#: on every release without touching code.
APP_REVISION = settings.app_version

#: What every conditional answer says about caching. See the module docstring.
CACHE_CONTROL = "private, no-cache"

#: Long enough that a collision needs 2^64 distinct versions of one endpoint,
#: short enough to stay a small header. This is a version tag, not a
#: signature — an attacker gains nothing by forging one but a stale screen of
#: their own — so a truncated digest is the right trade.
_TOKEN_LENGTH = 16


def _part(value: object) -> str:
    """One component of a version, rendered so equal states render equally.

    `str()` on a datetime is stable, but `str()` on a dict is not: Python
    preserves insertion order, so two dicts holding the same thing in a
    different order would hash differently and evict each other forever. Any
    mapping is therefore sorted before it is rendered.
    """
    if value is None:
        return "~"
    if isinstance(value, datetime):
        # Microseconds included on purpose: two writes inside one second are
        # ordinary, and a second-resolution validator would serve the first
        # answer for the second write.
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
    """A short, stable identifier for one state of one answer.

    Deliberately a digest of the inputs rather than a counter. A counter has
    to live somewhere — a column, or a number in this process that the other
    process does not have — and gets forgotten by exactly the writer that
    mattered. A digest of the state has no such failure: change anything the
    answer depends on and the token changes, in every process, with nobody
    having to remember.
    """
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
    """Whether the client already holds this version.

    `*` matches anything that exists, which is what the specification says and
    what a client sends when it means "only if you have nothing new". The
    comparison ignores the `W/` prefix because `If-None-Match` uses the weak
    comparison function: `W/"x"` and `"x"` are the same entity here.
    """
    if not if_none_match:
        return False

    wanted = etag.removeprefix("W/")
    for candidate in _candidates(if_none_match):
        if candidate == "*" or candidate.removeprefix("W/") == wanted:
            return True
    return False


def not_modified(etag: str) -> Response:
    """A bodiless 304 carrying the validators the client should keep.

    A 304 repeats `ETag` and `Cache-Control` deliberately: the client is
    updating a stored entry from this answer, and one that arrived without
    them would be stored with no validator and could never be revalidated
    again.
    """
    return Response(
        status_code=304,
        headers={"ETag": etag, "Cache-Control": CACHE_CONTROL},
    )


def apply(response: Response, etag: str) -> None:
    """Stamp a normal 200 so the next request can be conditional."""
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = CACHE_CONTROL


def route_label(request: Request) -> str:
    """The route's template, never the URL that arrived.

    `/api/forecasts/{run_id}` is one timeseries; `/api/forecasts/<a uuid>` is
    one per run, which is how a metrics endpoint quietly becomes the largest
    response the service serves. Starlette records the matched route on the
    scope, and the fallback is only reached before routing has happened.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else request.url.path


#: What a conditional read adds to its OpenAPI entry. Documented rather than
#: left implicit: a client that does not know 304 is possible will treat the
#: empty body as an empty answer and render a dashboard of zeroes.
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
    """A token that changes when a response model's shape changes.

    The problem this solves is quiet and nasty. A browser holds a body and an
    `ETag`. A deploy renames a field. The data behind the answer has not
    changed, so the token has not changed, so the browser is told 304 and goes
    on rendering last week's shape against this week's frontend.

    A hand-maintained "bump this when you change the response" constant is the
    usual fix and it is the kind that gets forgotten by exactly the change
    that needed it. The model's own JSON schema cannot be forgotten: add a
    field, drop one, change a type, and the schema differs, so the token
    differs, so every client refetches once. It is identical across processes
    running the same build, which a per-process nonce would not be — that
    version works for one uvicorn and silently stops working for two.

    Memoised because generating a JSON schema is not free and the answer is
    fixed for the life of the process.

    It does not catch a change to how a number is *computed* — same shape,
    different value. `APP_REVISION` covers the release that carries such a
    change, and the entries this process holds are gone at restart regardless.
    """
    schema = json.dumps(model.model_json_schema(), sort_keys=True, default=str)
    return hashlib.blake2b(schema.encode("utf-8"), digest_size=4).hexdigest()


def conditional(request: Request, response: Response, token: str) -> Response | None:
    """The whole handshake in one call.

    Returns a 304 to hand straight back when the client is up to date, or
    `None` after stamping `response` with the validators, meaning "go ahead
    and compute the answer".
    """
    etag = etag_for(token)
    label = route_label(request)

    if matches(request.headers.get("if-none-match"), etag):
        metrics.conditional_responses.inc(route=label, outcome="not_modified")
        return not_modified(etag)

    metrics.conditional_responses.inc(route=label, outcome="rendered")
    apply(response, etag)
    return None
