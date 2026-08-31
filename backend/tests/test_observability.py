"""What a scrape says, and what it must never be able to do to the process.

Named for the subject rather than the module: `test_metrics.py` is already
taken by the forecast accuracy metrics, and two files with that name a
directory apart is the sort of thing that gets one of them deleted.
"""

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
    """A counter that can fall reads to the scraper as a process restart.

    `rate()` sees the drop, assumes a reset, and reports a spike that never
    happened — on the graph somebody is about to page off.
    """
    with pytest.raises(ValueError, match="cannot be decremented"):
        Counter("t_total", "help").inc(-1)


def test_a_gauge_moves_in_both_directions() -> None:
    gauge = Gauge("t", "help")

    gauge.inc()
    gauge.inc()
    gauge.dec()

    assert gauge.value() == 1.0


def test_histogram_buckets_are_cumulative() -> None:
    """`le` means "at most", so every bucket includes the ones below it."""
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
    """One NaN makes `_sum` NaN forever, and every quantile with it."""
    histogram = Histogram("t_seconds", "help")

    histogram.observe(1.0)
    histogram.observe(math.nan)

    assert histogram.count_of() == 1.0
    assert not math.isnan(histogram.sum_of())


def test_label_cardinality_is_capped_and_the_total_stays_true() -> None:
    """An unbounded label is a memory leak with a public trigger.

    One series per request path means one per UUID in a URL, which is a
    hundred thousand timeseries after a week and an exposition response
    measured in megabytes. Past the cap the excess folds into one overflow
    series: the breakdown stops being useful, the total does not stop being
    right.
    """
    counter = Counter("t_total", "help", ("path",))

    for index in range(metrics.MAX_SERIES + 50):
        counter.inc(path=f"/thing/{index}")

    assert len(counter.samples()) == metrics.MAX_SERIES + 1
    assert counter.overflowed is True
    assert sum(value for _, _, value in counter.samples()) == metrics.MAX_SERIES + 50


def test_a_missing_label_costs_a_dimension_not_a_request() -> None:
    """These sit in the request path. Raising here would take the answer down."""
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
    """Python writes `inf`; the exposition format demands `+Inf`."""
    registry = Registry()
    registry.histogram("t_seconds", "help", buckets=(1.0,)).observe(0.5)

    assert 't_seconds_bucket{le="+Inf"} 1' in registry.render()


def test_registering_the_same_name_twice_returns_the_one_metric() -> None:
    """A double import is not a second metric.

    The library version of this raises at import time, in a module global,
    which the test suite and Celery's fork both trip over — and the traceback
    points at the import rather than at anything anybody can fix.
    """
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
    """`/api/forecasts/{run_id}` is one series. The URL is one per run."""
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
    """403 confirms the endpoint exists. A deployment that turned it off said no."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "metrics_enabled", False)

    assert (await client.get("/api/health/metrics")).status_code == 404


async def test_a_scrape_does_not_spend_the_rate_limit_allowance(client: AsyncClient) -> None:
    """Scrapes arrive every fifteen seconds forever. Health is exempt for the
    same reason, and this endpoint lives under that prefix to inherit it."""
    for _ in range(5):
        response = await client.get("/api/health/metrics")
        assert response.status_code == 200
        assert "RateLimit-Limit" not in response.headers


async def test_a_failing_request_is_counted_as_a_failure(client: AsyncClient) -> None:
    """An error rate that improves during an outage is worse than no error rate."""
    await client.get("/api/dashboard/breakdown")  # missing required query param -> 422

    body = (await client.get("/api/health/metrics")).text

    assert 'status="4xx"' in body


async def test_production_with_no_token_refuses_every_scrape(
    client: AsyncClient, monkeypatch
) -> None:
    """An unset token in production is a mistake, not a decision.

    Refusing to boot over it was the other option and is the wrong one: this
    leaks route names and error rates, which is worth closing and is not worth
    an outage on somebody's next deploy. Refused here, warned about at
    startup.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "metrics_token", "")

    assert (await client.get("/api/health/metrics")).status_code == 401
    assert settings.metrics_need_a_token is True


def test_a_configured_token_is_enough_anywhere() -> None:
    from app.core.config import settings

    assert settings.metrics_need_a_token is False
