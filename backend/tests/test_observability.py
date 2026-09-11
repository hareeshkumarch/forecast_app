from __future__ import annotations

import math

import pytest
from httpx import AsyncClient

from app.core import metrics
from app.core.metrics import Counter, Gauge, Histogram, Registry


@pytest.fixture(autouse=True)
def _counters_start_at_zero():
    metrics.registry.reset()
    yield
    metrics.registry.reset()


def test_a_counter_adds_up_per_label_set() -> None:
    counter = Counter("t_total", "help", ("route",))

    counter.inc(route="/a")
    counter.inc(2.0, route="/a")
    counter.inc(route="/b")

    assert counter.value(route="/a") == 3.0
    assert counter.value(route="/b") == 1.0


def test_a_counter_refuses_to_go_backwards() -> None:
    with pytest.raises(ValueError, match="cannot be decremented"):
        Counter("t_total", "help").inc(-1)


def test_a_gauge_moves_in_both_directions() -> None:
    gauge = Gauge("t", "help")

    gauge.inc()
    gauge.inc()
    gauge.dec()

    assert gauge.value() == 1.0


def test_histogram_buckets_are_cumulative() -> None:
    histogram = Histogram("t_seconds", "help", buckets=(0.1, 1.0))

    for value in (0.05, 0.5, 5.0):
        histogram.observe(value)

    counts = {
        labels[-1][1]: value
        for name, labels, value in histogram.samples()
        if name.endswith("_bucket")
    }
    assert counts == {"0.1": 1.0, "1": 2.0, "+Inf": 3.0}
    assert histogram.count_of() == 3.0
    assert histogram.sum_of() == pytest.approx(5.55)


def test_a_nan_observation_is_dropped_rather_than_poisoning_the_sum() -> None:
    histogram = Histogram("t_seconds", "help")

    histogram.observe(1.0)
    histogram.observe(math.nan)

    assert histogram.count_of() == 1.0
    assert not math.isnan(histogram.sum_of())


def test_label_cardinality_is_capped_and_the_total_stays_true() -> None:
    counter = Counter("t_total", "help", ("path",))

    for index in range(metrics.MAX_SERIES + 50):
        counter.inc(path=f"/thing/{index}")

    assert len(counter.samples()) == metrics.MAX_SERIES + 1
    assert counter.overflowed is True
    assert sum(value for _, _, value in counter.samples()) == metrics.MAX_SERIES + 50


def test_a_missing_label_costs_a_dimension_not_a_request() -> None:
    counter = Counter("t_total", "help", ("route", "method"))

    counter.inc(route="/a")

    assert counter.value(route="/a", method="") == 1.0


def test_rendering_is_prometheus_text_format() -> None:
    registry = Registry()
    counter = registry.counter("t_total", "How many things.", ("kind",))
    counter.inc(3, kind='a "quoted" one')

    rendered = registry.render()

    assert "# HELP t_total How many things." in rendered
    assert "# TYPE t_total counter" in rendered
    assert 't_total{kind="a \\"quoted\\" one"} 3' in rendered
    assert rendered.endswith("\n")


def test_infinity_renders_the_way_prometheus_spells_it() -> None:
    registry = Registry()
    registry.histogram("t_seconds", "help", buckets=(1.0,)).observe(0.5)

    assert 't_seconds_bucket{le="+Inf"} 1' in registry.render()


def test_registering_the_same_name_twice_returns_the_one_metric() -> None:
    registry = Registry()

    first = registry.counter("t_total", "help")
    second = registry.counter("t_total", "help")

    first.inc()
    assert second is first
    assert second.value() == 1.0


async def test_the_endpoint_serves_what_the_middleware_recorded(client: AsyncClient) -> None:
    await client.get("/api/health")

    body = (await client.get("/api/health/metrics")).text

    assert "forecasting_http_requests_total" in body
    assert 'route="/api/health"' in body
    assert "forecasting_http_request_duration_seconds_bucket" in body


async def test_the_endpoint_labels_by_route_template_not_by_url(client: AsyncClient) -> None:
    await client.get("/api/forecasts/00000000-0000-0000-0000-000000000000")

    body = (await client.get("/api/health/metrics")).text

    assert 'route="/api/forecasts/{run_id}"' in body
    assert "00000000-0000-0000-0000-000000000000" not in body


async def test_the_endpoint_answers_in_the_content_type_a_scraper_expects(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/health/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in response.headers["content-type"]


async def test_a_configured_token_is_required(client: AsyncClient, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "metrics_token", "s3cret-scrape-token")

    assert (await client.get("/api/health/metrics")).status_code == 401
    assert (
        await client.get("/api/health/metrics", headers={"Authorization": "Bearer wrong"})
    ).status_code == 401
    assert (
        await client.get(
            "/api/health/metrics", headers={"Authorization": "Bearer s3cret-scrape-token"}
        )
    ).status_code == 200


async def test_metrics_off_answers_404_rather_than_403(client: AsyncClient, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "metrics_enabled", False)

    assert (await client.get("/api/health/metrics")).status_code == 404


async def test_a_scrape_does_not_spend_the_rate_limit_allowance(client: AsyncClient) -> None:
    for _ in range(5):
        response = await client.get("/api/health/metrics")
        assert response.status_code == 200
        assert "RateLimit-Limit" not in response.headers


async def test_a_failing_request_is_counted_as_a_failure(client: AsyncClient) -> None:
    await client.get("/api/dashboard/breakdown")

    body = (await client.get("/api/health/metrics")).text

    assert 'status="4xx"' in body


async def test_production_with_no_token_refuses_every_scrape(
    client: AsyncClient, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "metrics_token", "")

    assert (await client.get("/api/health/metrics")).status_code == 401
    assert settings.metrics_need_a_token is True


def test_a_configured_token_is_enough_anywhere() -> None:
    from app.core.config import settings

    assert settings.metrics_need_a_token is False


class TestSecurityHeaders:
    async def test_every_answer_carries_them(self, client) -> None:
        response = await client.get("/api/health")

        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "camera=()" in response.headers["Permissions-Policy"]

    async def test_a_refusal_carries_them_too(self, client) -> None:
        response = await client.get("/api/datasets/not-a-uuid")

        assert response.status_code >= 400
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    async def test_hsts_is_not_sent_over_plain_http(self, client) -> None:
        response = await client.get("/api/health")

        assert "Strict-Transport-Security" not in response.headers

    async def test_hsts_is_sent_where_the_proxy_says_the_hop_was_tls(self, client) -> None:
        response = await client.get("/api/health", headers={"X-Forwarded-Proto": "https"})

        assert "max-age=" in response.headers["Strict-Transport-Security"]
