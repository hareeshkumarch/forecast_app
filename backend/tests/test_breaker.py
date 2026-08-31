"""A dependency having a bad minute must cost one timeout, not eighty."""

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
    """The distinction the whole design rests on.

    401, 403 and 404 arrive promptly, cost nothing, and are fixed by somebody
    changing a setting. Tripping on them would mean the person who has just
    pasted a corrected key waits out a cooldown to find out it works — a
    breaker making the product worse than no breaker.
    """
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
    """Three timeouts spread over an afternoon are not an outage."""
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
    """Releasing the whole backlog at the cooldown re-floors a sick service."""
    guard = CircuitBreaker("t", failure_threshold=1, reset_timeout_seconds=0.05)

    guard.record_failure()
    time.sleep(0.08)

    assert guard.allows() is True
    assert guard.allows() is False
    assert guard.allows() is False


def test_a_failed_trial_reopens_at_once() -> None:
    """The one call allowed through is the whole evidence.

    Making it earn the full threshold again would send three more requests
    into something already known to be down.
    """
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
    """`call` decides by the exception, not by whether it raised at all."""
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
    """Pulling an instance out of service because an optional nicety is down
    turns somebody else's outage into ours, at the moment the instances that
    are still up can least afford it."""
    # Driven to its own threshold rather than assuming one: `breaker()` shares
    # by name, so whichever test registered "llm:openai" first decided what
    # that number is.
    guard = breaker_module.breaker("llm:openai")
    for _ in range(guard.failure_threshold):
        guard.record_failure()

    body = (await client.get("/api/health")).json()

    assert body["status"] == "ok"
    states = {row["name"]: row["state"] for row in body["dependencies"]}
    assert states["llm:openai"] == "open"


def test_a_dead_provider_stops_being_called_after_the_threshold(monkeypatch) -> None:
    """The reason this exists at all.

    Eight insights fanned out at a provider that is timing out used to be
    eight full timeouts, every time somebody pressed the button. Now the first
    few pay for the discovery and the rest are refused for nothing.

    Under a provider name of its own, because `breaker()` shares by name and
    configures only on the call that creates one — so a test that assumed a
    threshold for `llm:openai` would pass or fail on whichever test file
    happened to register that breaker first. Its own name makes it the
    creator, and reading the threshold back rather than assuming it makes it
    true even if that stops being so.
    """
    from app.insights import llm
    from app.insights.generators import GeneratedInsight
    from app.insights.llm import rewrite_insights
    from app.models.enums import InsightSeverity, InsightType

    provider = "breaker-probe"
    calls = 0

    def timing_out(source: str, config: dict[str, object] | None = None):
        nonlocal calls
        calls += 1
        # Shaped like the real client's own answer rather than raising. A
        # stub that raises turns a wrong assumption in this test into a
        # thread exception three frames away from the assertion that meant it.
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
    """The liveness bug a boolean flag hides.

    A caller that claims the one half-open trial and never reports back — a
    thread that died, a path that returned early — would leave the breaker
    refusing everything forever, with no failure anywhere to explain it. The
    claim expires on the same cooldown that granted it.
    """
    guard = CircuitBreaker("t", failure_threshold=1, reset_timeout_seconds=0.05)

    guard.record_failure()
    time.sleep(0.08)
    assert guard.allows() is True  # claimed, and deliberately never reported
    assert guard.allows() is False

    time.sleep(0.08)

    assert guard.allows() is True


def test_a_caller_that_does_not_call_hands_the_trial_back() -> None:
    guard = CircuitBreaker("t", failure_threshold=1, reset_timeout_seconds=30.0)

    guard.record_failure()
    guard._opened_at = time.monotonic() - 31.0  # cooled down
    assert guard.allows() is True

    guard.release_trial()

    assert guard.allows() is True
