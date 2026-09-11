from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

from app.core.middleware import CompressExceptStreams

PAYLOAD = {"rows": [{"period": f"2026-{m:02d}-01", "forecast": 1000 + m} for m in range(1, 13)] * 8}


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.add_middleware(CompressExceptStreams)

    @application.get("/api/forecasts")
    async def forecasts() -> dict:
        return PAYLOAD

    @application.get("/api/tiny")
    async def tiny() -> dict:
        return {"ok": True}

    @application.get("/api/forecasts/{run_id}/events")
    async def events(run_id: str) -> StreamingResponse:
        async def stream() -> AsyncIterator[bytes]:
            for i in range(3):
                yield f'data: {{"progress": {i / 2}}}\n\n'.encode()
                await asyncio.sleep(0)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return application


async def _get(app: FastAPI, path: str, gzip: bool = True):
    headers = {"Accept-Encoding": "gzip"} if gzip else {"Accept-Encoding": "identity"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(path, headers=headers)


async def test_a_json_response_is_compressed(app: FastAPI) -> None:
    response = await _get(app, "/api/forecasts")
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"


async def test_compression_actually_shrinks_the_payload(app: FastAPI) -> None:
    compressed = await _get(app, "/api/forecasts")
    plain = await _get(app, "/api/forecasts", gzip=False)

    on_the_wire = int(compressed.headers["content-length"])
    uncompressed = len(plain.content)
    assert on_the_wire < uncompressed / 2
    assert compressed.json() == plain.json()


async def test_a_small_response_is_left_alone(app: FastAPI) -> None:
    response = await _get(app, "/api/tiny")
    assert response.headers.get("content-encoding") is None


async def test_the_progress_stream_is_never_compressed(app: FastAPI) -> None:
    response = await _get(app, "/api/forecasts/abc-123/events")
    assert response.status_code == 200
    assert response.headers.get("content-encoding") is None
    assert response.headers["content-type"].startswith("text/event-stream")


async def test_the_stream_still_carries_its_frames(app: FastAPI) -> None:
    response = await _get(app, "/api/forecasts/abc-123/events")
    assert response.text.count("data: ") == 3


async def test_a_client_that_cannot_decompress_gets_plain_bytes(app: FastAPI) -> None:
    response = await _get(app, "/api/forecasts", gzip=False)
    assert response.headers.get("content-encoding") is None
    assert response.json() == PAYLOAD
