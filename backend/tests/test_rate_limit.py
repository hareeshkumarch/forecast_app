"""One busy client must not be able to slow the platform for everybody else."""

from __future__ import annotations

import pytest

from app.core import ratelimit
from app.core.ratelimit import Rule, SlidingWindow


@pytest.fixture(autouse=True)
def _clean():
    ratelimit.limiter.forget_all()
    yield
    ratelimit.limiter.forget_all()


def test_a_client_is_allowed_up_to_the_limit_and_then_refused() -> None:
    window = SlidingWindow()
    rule = Rule(limit=3, window_seconds=60, name="t")

    assert [window.check("a", rule, now=1.0)[0] for _ in range(3)] == [True, True, True]
    assert window.check("a", rule, now=1.0)[0] is False


def test_remaining_counts_down_and_reaches_zero() -> None:
    window = SlidingWindow()
    rule = Rule(limit=3, window_seconds=60, name="t")

    assert [window.check("a", rule, now=1.0)[1] for _ in range(3)] == [2, 1, 0]


def test_clients_are_counted_separately() -> None:
    window = SlidingWindow()
    rule = Rule(limit=1, window_seconds=60, name="t")

    assert window.check("a", rule, now=1.0)[0] is True
    assert window.check("b", rule, now=1.0)[0] is True


def test_rules_are_counted_separately_for_one_client() -> None:
    """Spending an upload allowance must not stop somebody reading a page."""
    window = SlidingWindow()
    one = Rule(limit=1, window_seconds=60, name="one")
    two = Rule(limit=1, window_seconds=60, name="two")

    assert window.check("a", one, now=1.0)[0] is True
    assert window.check("a", two, now=1.0)[0] is True


def test_the_window_slides_rather_than_resetting() -> None:
    """A fixed window allows twice the limit across its boundary.

    Spend the allowance in the last moment of one window and the whole of the
    next in the first moment of the next, and a limit of three has passed six
    requests in a blink — which is the burst the limit exists to stop.
    """
    window = SlidingWindow()
    rule = Rule(limit=3, window_seconds=60, name="t")

    for _ in range(3):
        window.check("a", rule, now=59.0)
    assert window.check("a", rule, now=60.1)[0] is False, "a fixed window would have allowed this"
    assert window.check("a", rule, now=119.5)[0] is True, "the oldest has aged out by now"


def test_a_refusal_is_not_counted_against_the_client() -> None:
    """Otherwise somebody who keeps retrying never comes off the limit.

    Counting refusals turns a momentary burst into an indefinite block, and
    the client least likely to stop retrying is the one least likely to
    deserve it.
    """
    window = SlidingWindow()
    rule = Rule(limit=1, window_seconds=10, name="t")

    window.check("a", rule, now=0.0)
    for _ in range(50):
        window.check("a", rule, now=5.0)

    assert window.check("a", rule, now=10.5)[0] is True


def test_tracking_is_bounded() -> None:
    """A map keyed by remote address is a memory leak with a public trigger."""
    window = SlidingWindow(max_tracked=10)
    rule = Rule(limit=5, window_seconds=60, name="t")

    for n in range(500):
        window.check(f"client-{n}", rule, now=1.0)

    assert window.tracked <= 10


def test_retry_after_is_never_zero() -> None:
    window = SlidingWindow()
    rule = Rule(limit=1, window_seconds=60, name="t")
    window.check("a", rule, now=1.0)

    allowed, _, reset = window.check("a", rule, now=60.9)
    assert allowed is False
    assert reset >= 1


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/health", None),
        ("GET", "/api/health/features", None),
        ("GET", "/api/forecasts/abc/events", None),
        ("GET", "/api/auth/events", None),
        ("GET", "/api/auth/decide", ratelimit.DECIDE),
        ("POST", "/api/auth/invite", ratelimit.ADMIN),
        ("GET", "/api/auth/users", ratelimit.DEFAULT),
        ("POST", "/api/forecasts", ratelimit.RUN),
        ("POST", "/api/datasets", ratelimit.UPLOAD),
        ("GET", "/api/dashboard/summary", ratelimit.DEFAULT),
    ],
)
def test_each_route_lands_on_the_rule_meant_for_it(method, path, expected) -> None:
    assert ratelimit.rule_for(method, path) is expected


def test_health_is_never_limited() -> None:
    """A rate-limited health check reads as an outage.

    The deploy script polls it in a loop for up to fifteen minutes while an
    image builds.
    """
    assert ratelimit.rule_for("GET", "/api/health") is None


def test_the_progress_stream_is_never_limited() -> None:
    """It is one long-lived connection, not a request rate."""
    assert ratelimit.rule_for("GET", "/api/forecasts/x/events") is None


def test_identity_prefers_the_forwarded_client() -> None:
    assert ratelimit.client_identity({"x-forwarded-for": "1.2.3.4, 5.6.7.8"}, "10.0.0.1") == "1.2.3.4"
    assert ratelimit.client_identity({"x-real-ip": "1.2.3.4"}, "10.0.0.1") == "1.2.3.4"
    assert ratelimit.client_identity({}, "10.0.0.1") == "10.0.0.1"
    assert ratelimit.client_identity({}, None) == "unknown"


async def test_the_headers_are_served_on_an_ordinary_answer(client) -> None:
    """A client that can see it has four left can slow down.

    One that only finds out at zero cannot, which is how a well-behaved
    integration ends up looking like an attack.
    """
    response = await client.get("/api/auth/decide", params={"token": "nope"})

    assert response.headers["RateLimit-Limit"] == str(ratelimit.DECIDE.limit)
    assert int(response.headers["RateLimit-Remaining"]) == ratelimit.DECIDE.limit - 1
    assert int(response.headers["RateLimit-Reset"]) >= 1


async def test_going_over_is_answered_as_429_in_the_platform_error_shape(client) -> None:
    for _ in range(ratelimit.DECIDE.limit):
        await client.get("/api/auth/decide", params={"token": "nope"})

    response = await client.get("/api/auth/decide", params={"token": "nope"})

    assert response.status_code == 429
    assert response.headers["Retry-After"]
    assert response.headers["RateLimit-Remaining"] == "0"

    body = response.json()["error"]
    assert body["code"] == "rate_limited"
    assert body["detail"]["retry_after_seconds"] >= 1
    # Every other error this platform serves carries one, and a client that
    # reports a problem quotes it. A 429 without one is the answer nobody can
    # trace afterwards.
    assert body["request_id"]


async def test_health_survives_a_hammering(client) -> None:
    """The deploy script polls this in a loop while an image builds."""
    for _ in range(ratelimit.DEFAULT.limit + 50):
        response = await client.get("/api/health")
        assert response.status_code == 200
    assert "RateLimit-Limit" not in response.headers
