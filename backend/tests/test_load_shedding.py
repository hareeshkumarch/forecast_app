"""Past a ceiling, refusing quickly beats answering slowly."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.middleware import ConcurrencyLimitMiddleware


def _app(limit: int, *, enabled: bool = True, hold: asyncio.Event | None = None) -> Starlette:
    async def slow(_request):
        if hold is not None:
            await hold.wait()
        return PlainTextResponse("done")

    async def quick(_request):
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[
            Route("/api/work", slow),
            Route("/api/health", quick),
            Route("/api/forecasts/1/events", quick),
        ]
    )
    app.add_middleware(ConcurrencyLimitMiddleware, limit=limit, enabled=enabled)
    return app


def _client(app: Starlette) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_requests_past_the_ceiling_are_refused_immediately() -> None:
    hold = asyncio.Event()
    async with _client(_app(2, hold=hold)) as client:
        first = asyncio.create_task(client.get("/api/work"))
        second = asyncio.create_task(client.get("/api/work"))
        await asyncio.sleep(0.05)

        shed = await client.get("/api/work")

        assert shed.status_code == 503
        assert shed.json()["error"]["code"] == "overloaded"
        assert shed.headers["Retry-After"] == "2"
        assert shed.json()["error"]["detail"]["concurrency_limit"] == 2

        hold.set()
        assert (await first).status_code == 200
        assert (await second).status_code == 200


async def test_a_slot_is_returned_when_the_request_finishes() -> None:
    """A leak here shows up as a service that refuses everything after an hour."""
    hold = asyncio.Event()
    app = _app(1, hold=hold)
    async with _client(app) as client:
        inflight = asyncio.create_task(client.get("/api/work"))
        await asyncio.sleep(0.05)
        assert (await client.get("/api/work")).status_code == 503

        hold.set()
        await inflight

        hold.clear()
        hold.set()
        assert (await client.get("/api/work")).status_code == 200


async def test_health_is_never_shed() -> None:
    """The load balancer decides this instance is alive by asking it.

    An instance that sheds its own health check gets taken out of service at
    exactly the moment the traffic needs somewhere to go.
    """
    hold = asyncio.Event()
    async with _client(_app(1, hold=hold)) as client:
        inflight = asyncio.create_task(client.get("/api/work"))
        await asyncio.sleep(0.05)

        assert (await client.get("/api/health")).status_code == 200

        hold.set()
        await inflight


async def test_a_progress_stream_does_not_hold_a_slot() -> None:
    """A stream is open for the length of a forecast run.

    Counting them would let a handful of open dashboards consume the whole
    allowance and shed every other request on the box.
    """
    hold = asyncio.Event()
    async with _client(_app(1, hold=hold)) as client:
        inflight = asyncio.create_task(client.get("/api/work"))
        await asyncio.sleep(0.05)

        assert (await client.get("/api/forecasts/1/events")).status_code == 200

        hold.set()
        await inflight


async def test_shedding_can_be_switched_off_for_a_load_test() -> None:
    hold = asyncio.Event()
    async with _client(_app(1, enabled=False, hold=hold)) as client:
        first = asyncio.create_task(client.get("/api/work"))
        second = asyncio.create_task(client.get("/api/work"))
        await asyncio.sleep(0.05)

        hold.set()
        assert [(await first).status_code, (await second).status_code] == [200, 200]


async def test_a_shed_request_is_counted_against_a_bounded_label() -> None:
    """The path has not been routed yet, so there is no template to use.

    The first two segments are bounded; the raw path would be one timeseries
    per URL, which is how a metrics endpoint becomes the largest response a
    service serves.
    """
    from app.core import metrics

    metrics.registry.reset()
    hold = asyncio.Event()
    async with _client(_app(1, hold=hold)) as client:
        inflight = asyncio.create_task(client.get("/api/work"))
        await asyncio.sleep(0.05)
        await client.get("/api/work")
        hold.set()
        await inflight

    assert metrics.http_shed.value(route="/api/work") == 1.0


def test_a_ceiling_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one request"):
        ConcurrencyLimitMiddleware(_app(1), limit=0)
