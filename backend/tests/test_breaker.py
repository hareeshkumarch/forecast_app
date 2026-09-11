from __future__ import annotations

import time

import httpx
import pytest
from httpx import AsyncClient

from app.core import breaker as breaker_module
from app.core.breaker import (
    BreakerState,
    CircuitBreaker,
    CircuitOpenError,
    is_transport_failure,
)
from app.insights.llm import LlmCallResult, LlmUsageRecord


@pytest.fixture(autouse=True)
def _breakers_start_closed():
    breaker_module.reset_all()
    yield
    breaker_module.reset_all()


def _status(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.example/v1/chat")
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(code, request=request)
    )


def test_a_wrong_key_is_not_an_outage() -> None:
    assert is_transport_failure(_status(401)) is False
    assert is_transport_failure(_status(403)) is False
    assert is_transport_failure(_status(404)) is False
    assert is_transport_failure(ValueError("the model said something odd")) is False


def test_a_provider_that_is_struggling_counts() -> None:
    assert is_transport_failure(_status(429)) is True
    assert is_transport_failure(_status(500)) is True
    assert is_transport_failure(_status(503)) is True
    assert is_transport_failure(httpx.ConnectTimeout("timed out")) is True
    assert is_transport_failure(httpx.ConnectError("refused")) is True
    assert is_transport_failure(TimeoutError()) is True


def test_it_opens_only_after_the_threshold() -> None:
    guard = CircuitBreaker("t", failure_threshold=3)

    for _ in range(2):
        guard.record_failure()
    assert guard.state is BreakerState.CLOSED

    guard.record_failure()
    assert guard.state is BreakerState.OPEN


def test_a_success_forgives_what_came_before() -> None:
    guard = CircuitBreaker("t", failure_threshold=3)

    guard.record_failure()
    guard.record_failure()
    guard.record_success()
    guard.record_failure()

    assert guard.state is BreakerState.CLOSED


def test_an_open_breaker_refuses_without_calling() -> None:
    guard = CircuitBreaker("t", failure_threshold=1)
    calls = 0

    def call() -> str:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        guard.call(call)

    with pytest.raises(CircuitOpenError) as refused:
        guard.call(call)

    assert calls == 1
    assert refused.value.status_code == 503
    assert refused.value.detail["retry_after_seconds"] >= 1


def test_half_open_admits_exactly_one_trial() -> None:
    guard = CircuitBreaker("t", failure_threshold=1, reset_timeout_seconds=0.05)

    guard.record_failure()
    time.sleep(0.08)

    assert guard.allows() is True
    assert guard.allows() is False
    assert guard.allows() is False


def test_a_failed_trial_reopens_at_once() -> None:
    guard = CircuitBreaker("t", failure_threshold=4, reset_timeout_seconds=0.05)

    for _ in range(4):
        guard.record_failure()
    time.sleep(0.08)
    assert guard.state is BreakerState.HALF_OPEN

    guard.allows()
    guard.record_failure()

    assert guard.state is BreakerState.OPEN


def test_a_successful_trial_closes_it_for_everybody() -> None:
    guard = CircuitBreaker("t", failure_threshold=1, reset_timeout_seconds=0.05)

    guard.record_failure()
    time.sleep(0.08)
    assert guard.call(lambda: "fine") == "fine"

    assert guard.state is BreakerState.CLOSED
    assert guard.allows() is True


def test_an_answer_that_is_not_an_outage_keeps_the_circuit_closed() -> None:
    guard = CircuitBreaker("t", failure_threshold=1)

    with pytest.raises(httpx.HTTPStatusError):
        guard.call(lambda: (_ for _ in ()).throw(_status(401)))

    assert guard.state is BreakerState.CLOSED


def test_breakers_are_shared_by_name_and_reported_together() -> None:
    first = breaker_module.breaker("llm:openai")
    again = breaker_module.breaker("llm:openai")
    other = breaker_module.breaker("llm:anthropic")

    first.record_failure()

    assert again is first
    assert other is not first
    assert [row.name for row in breaker_module.snapshots()] == ["llm:anthropic", "llm:openai"]
    assert [row.healthy for row in breaker_module.snapshots()] == [True, True]


def test_a_breaker_refuses_a_configuration_that_could_never_open_or_close() -> None:
    with pytest.raises(ValueError, match="at least one failure"):
        CircuitBreaker("t", failure_threshold=0)
    with pytest.raises(ValueError, match="cooldown must be positive"):
        CircuitBreaker("t", reset_timeout_seconds=0)


async def test_health_reports_the_state_without_calling_the_deployment_degraded(
    client: AsyncClient,
) -> None:
    guard = breaker_module.breaker("llm:openai")
    for _ in range(guard.failure_threshold):
        guard.record_failure()

    body = (await client.get("/api/health")).json()

    assert body["status"] == "ok"
    states = {row["name"]: row["state"] for row in body["dependencies"]}
    assert states["llm:openai"] == "open"


def test_a_dead_provider_stops_being_called_after_the_threshold(monkeypatch) -> None:
    from app.insights import llm
    from app.insights.generators import GeneratedInsight
    from app.insights.llm import rewrite_insights
    from app.models.enums import InsightSeverity, InsightType

    provider = "breaker-probe"
    calls = 0

    def timing_out(source: str, config: dict[str, object] | None = None):
        nonlocal calls
        calls += 1
        return LlmCallResult(
            text=None,
            usage=LlmUsageRecord(
                provider=provider,
                model="m",
                status="error",
                latency_ms=0.0,
                error_code="ConnectTimeout",
            ),
        )

    monkeypatch.setattr("app.insights.llm._call_llm_api", timing_out)

    drafts = [
        GeneratedInsight(
            type=kind,
            severity=InsightSeverity.INFO,
            title=f"Title {index}",
            explanation="Something happened.",
            suggested_action="Do something.",
            metric_name="m",
            metric_value=1.0,
            metric_unit="absolute",
            supporting_data={},
        )
        for index, kind in enumerate(list(InsightType)[:6])
    ]

    guard = llm.provider_breaker(provider)
    for _ in range(guard.failure_threshold):
        guard.record_failure()
    assert guard.state is BreakerState.OPEN

    usage: list = []
    rewrite_insights(drafts, {"llm_api_key": "k", "llm_provider": provider}, usage)

    assert calls == 0
    assert {record.error_code for record in usage} == {"circuit_open"}
    assert all(record.applied is False for record in usage)


def test_a_refused_call_says_so_in_words_a_person_can_read(monkeypatch) -> None:
    from app.services.insight_service import REFUSAL_REASONS

    assert "circuit_open" in REFUSAL_REASONS
    assert "skipped" in REFUSAL_REASONS["circuit_open"]


def test_an_abandoned_trial_does_not_wedge_the_breaker_shut() -> None:
    guard = CircuitBreaker("t", failure_threshold=1, reset_timeout_seconds=0.05)

    guard.record_failure()
    time.sleep(0.08)
    assert guard.allows() is True
    assert guard.allows() is False

    time.sleep(0.08)

    assert guard.allows() is True


def test_a_caller_that_does_not_call_hands_the_trial_back() -> None:
    guard = CircuitBreaker("t", failure_threshold=1, reset_timeout_seconds=30.0)

    guard.record_failure()
    guard._opened_at = time.monotonic() - 31.0
    assert guard.allows() is True

    guard.release_trial()

    assert guard.allows() is True
