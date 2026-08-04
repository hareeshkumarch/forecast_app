from __future__ import annotations

import logging
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import ConnectorError, NotFoundError, register_error_handlers
from app.core.logging import _JsonFormatter, request_id
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware


def build_probe_app() -> FastAPI:
    probe = FastAPI()
    probe.add_middleware(RequestContextMiddleware)
    register_error_handlers(probe)

    @probe.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("the wheels came off")

    @probe.get("/known")
    async def _known() -> None:
        raise ConnectorError(
            "The warehouse refused the connection.", detail={"host": "db.internal"}
        )

    return probe


@pytest.fixture
async def probe_client():
    transport = ASGITransport(app=build_probe_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def envelope(payload: dict) -> dict:
    assert set(payload) == {"error"}
    error = payload["error"]
    assert set(error) == {"code", "message", "detail", "request_id"}
    return error


async def test_every_endpoint_answers_with_a_request_id(client) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER]


async def test_a_supplied_request_id_is_echoed_back(client) -> None:
    response = await client.get("/api/health", headers={REQUEST_ID_HEADER: "trace-me-123"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-me-123"


async def test_a_known_failure_keeps_its_code_and_detail(probe_client) -> None:
    response = await probe_client.get("/known")

    assert response.status_code == 400
    error = envelope(response.json())
    assert error["code"] == "connector_error"
    assert error["message"] == "The warehouse refused the connection."
    assert error["detail"] == {"host": "db.internal"}
    assert error["request_id"]


async def test_an_unhandled_failure_never_leaks_the_exception(probe_client) -> None:
    response = await probe_client.get("/boom")

    assert response.status_code == 500
    error = envelope(response.json())
    assert error["code"] == "internal_error"
    assert "the wheels came off" not in error["message"]
    assert "RuntimeError" not in error["message"]
    assert error["request_id"]


async def test_a_missing_resource_uses_the_same_envelope(client) -> None:
    response = await client.get(f"/api/forecasts/{uuid.uuid4()}")

    assert response.status_code == 404
    error = envelope(response.json())
    assert error["code"] == "not_found"


async def test_an_unrouted_path_uses_the_same_envelope(client) -> None:
    response = await client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert envelope(response.json())["code"] == "not_found"


async def test_a_bad_payload_reports_fields_without_echoing_the_request(client) -> None:
    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": "not-a-uuid", "horizon": 9_000, "llm_api_key": "sk-secret-value"},
    )

    assert response.status_code == 422
    error = envelope(response.json())
    assert error["code"] == "validation_error"

    body = response.text
    assert "sk-secret-value" not in body, "the payload must never be echoed back"

    problems = error["detail"]["errors"]
    assert {"loc", "type", "msg"} == set(problems[0])
    assert any("dataset_id" in problem["loc"] for problem in problems)


async def test_an_unknown_field_is_refused_rather_than_ignored(client) -> None:
    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": str(uuid.uuid4()), "surprise": True},
    )

    assert response.status_code == 422
    assert envelope(response.json())["code"] == "validation_error"


def test_the_error_status_map_covers_what_the_api_raises() -> None:
    assert NotFoundError.status_code == 404
    assert NotFoundError.code == "not_found"
    assert ConnectorError.status_code == 400


def test_the_json_formatter_carries_the_request_id() -> None:
    import json

    token = request_id.set("fmt-test-1")
    try:
        record = logging.LogRecord(
            "app.test", logging.INFO, __file__, 1, "hello %s", ("world",), None
        )
        record.request_id = request_id.get()
        entry = json.loads(_JsonFormatter().format(record))
    finally:
        request_id.reset(token)

    assert entry["message"] == "hello world"
    assert entry["request_id"] == "fmt-test-1"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "app.test"
