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
    window = SlidingWindow()
    one = Rule(limit=1, window_seconds=60, name="one")
    two = Rule(limit=1, window_seconds=60, name="two")

    assert window.check("a", one, now=1.0)[0] is True
    assert window.check("a", two, now=1.0)[0] is True


def test_the_window_slides_rather_than_resetting() -> None:
    window = SlidingWindow()
    rule = Rule(limit=3, window_seconds=60, name="t")

    for _ in range(3):
        window.check("a", rule, now=59.0)
    assert window.check("a", rule, now=60.1)[0] is False, "a fixed window would have allowed this"
    assert window.check("a", rule, now=119.5)[0] is True, "the oldest has aged out by now"


def test_a_refusal_is_not_counted_against_the_client() -> None:
    window = SlidingWindow()
    rule = Rule(limit=1, window_seconds=10, name="t")

    window.check("a", rule, now=0.0)
    for _ in range(50):
        window.check("a", rule, now=5.0)

    assert window.check("a", rule, now=10.5)[0] is True


def test_tracking_is_bounded() -> None:
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
    assert ratelimit.rule_for("GET", "/api/health") is None


def test_the_progress_stream_is_never_limited() -> None:
    assert ratelimit.rule_for("GET", "/api/forecasts/x/events") is None


@pytest.fixture
def _declared_proxy(monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "rate_limit_trusted_proxies_raw", "10.0.0.0/8")


def test_identity_is_read_from_the_end_of_the_chain_the_proxies_wrote(_declared_proxy) -> None:
    assert (
        ratelimit.client_identity({"x-forwarded-for": "1.2.3.4, 5.6.7.8"}, "10.0.0.1") == "5.6.7.8"
    )
    assert ratelimit.client_identity({"x-real-ip": "1.2.3.4"}, "10.0.0.1") == "1.2.3.4"
    assert ratelimit.client_identity({}, "10.0.0.1") == "10.0.0.1"
    assert ratelimit.client_identity({}, None) == "unknown"


def test_a_caller_cannot_mint_an_allowance_by_writing_the_header_itself(_declared_proxy) -> None:
    forged = {"x-forwarded-for": "attacker-chose-this, 203.0.113.9"}
    assert ratelimit.client_identity(forged, "10.0.0.1") == "203.0.113.9"


def test_a_peer_outside_the_declared_proxies_is_counted_by_its_socket(_declared_proxy) -> None:
    forged = {"x-forwarded-for": "1.1.1.1, 2.2.2.2"}
    assert ratelimit.client_identity(forged, "198.51.100.4") == "198.51.100.4"


def test_a_second_proxy_is_accounted_for_by_configuration(_declared_proxy, monkeypatch) -> None:
    monkeypatch.setattr(ratelimit.settings, "rate_limit_trusted_proxy_hops", 2)

    chain = {"x-forwarded-for": "9.9.9.9, 203.0.113.9, 10.0.0.5"}
    assert ratelimit.client_identity(chain, "10.0.0.1") == "203.0.113.9"


def test_a_shorter_chain_than_configured_falls_back_rather_than_wrapping(
    _declared_proxy, monkeypatch
) -> None:
    monkeypatch.setattr(ratelimit.settings, "rate_limit_trusted_proxy_hops", 3)

    assert ratelimit.client_identity({"x-forwarded-for": "203.0.113.9"}, "10.0.0.1") == (
        "203.0.113.9"
    )


def test_a_header_from_somewhere_other_than_the_proxy_is_not_believed() -> None:
    settings = ratelimit.settings
    before = settings.rate_limit_trusted_proxies_raw
    settings.rate_limit_trusted_proxies_raw = "10.0.0.0/8"
    try:
        forged = {"x-forwarded-for": "1.1.1.1"}
        assert ratelimit.client_identity(forged, "10.0.0.1") == "1.1.1.1"
        assert ratelimit.client_identity(forged, "203.0.113.55") == "203.0.113.55"
        assert ratelimit.client_identity(forged, "not-an-address") == "not-an-address"
    finally:
        settings.rate_limit_trusted_proxies_raw = before


async def test_the_headers_are_served_on_an_ordinary_answer(client) -> None:
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
    assert body["request_id"]


async def test_health_survives_a_hammering(client) -> None:
    for _ in range(ratelimit.DEFAULT.limit + 50):
        response = await client.get("/api/health")
        assert response.status_code == 200
    assert "RateLimit-Limit" not in response.headers


def test_a_forwarded_for_header_is_ignored_when_no_proxy_is_declared(monkeypatch) -> None:
    monkeypatch.setattr(ratelimit.settings, "rate_limit_trusted_proxies_raw", "")

    identity = ratelimit.client_identity({"x-forwarded-for": "9.9.9.9"}, "203.0.113.7")

    assert identity == "203.0.113.7", "an undeclared proxy must not let a caller pick its bucket"


def test_a_forwarded_for_header_is_read_from_a_declared_proxy(monkeypatch) -> None:
    monkeypatch.setattr(ratelimit.settings, "rate_limit_trusted_proxies_raw", "203.0.113.0/24")

    identity = ratelimit.client_identity({"x-forwarded-for": "9.9.9.9"}, "203.0.113.7")

    assert identity == "9.9.9.9"


def test_rotating_the_header_cannot_buy_extra_requests(monkeypatch) -> None:
    monkeypatch.setattr(ratelimit.settings, "rate_limit_trusted_proxies_raw", "")
    window = SlidingWindow()
    rule = Rule(limit=2, window_seconds=60, name="t")

    allowed = [
        window.check(
            ratelimit.client_identity({"x-forwarded-for": f"9.9.9.{n}"}, "198.51.100.4"),
            rule,
            now=1.0,
        )[0]
        for n in range(4)
    ]

    assert allowed == [True, True, False, False]
