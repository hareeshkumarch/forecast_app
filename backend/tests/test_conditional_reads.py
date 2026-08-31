"""The dashboard must be able to say "nothing has changed" for nearly nothing.

These are the tests that make the caching safe to have. Every one of them is
really the same question asked about a different input: does a change to
something the answer depends on produce a different validator? If the answer
is ever no, the cache serves a stale figure and the ETag tells a browser to
keep one.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core import cache
from app.core.httpcache import etag_for, matches, shape_token, version_token
from app.database.sample_data import generate_csv_bytes
from app.insights.llm import LlmCallResult, LlmUsageRecord

READS = ("/api/dashboard/summary", "/api/dashboard/decision", "/api/dashboard/drivers")


async def _seed_and_run(client: AsyncClient) -> dict:
    upload = await client.post(
        "/api/datasets/upload",
        files={"file": ("sample.csv", generate_csv_bytes(), "text/csv")},
    )
    assert upload.status_code == 201, upload.text

    run = await client.post(
        "/api/forecasts/run",
        json={
            "dataset_id": upload.json()["dataset"]["id"],
            "region_column": "region",
            "category_column": "product_category",
            "horizon": 6,
        },
    )
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]

    async with client.stream("GET", f"/api/forecasts/{run_id}/events") as stream:
        async for _ in stream.aiter_lines():
            pass

    detail = await client.get(f"/api/forecasts/{run_id}")
    assert detail.json()["status"] == "completed", detail.json().get("error_message")
    return detail.json()


# ---- the token itself -----------------------------------------------------


def test_a_mapping_hashes_by_its_contents_not_its_insertion_order() -> None:
    """Two dicts holding the same thing must not evict each other forever."""
    assert version_token({"a": 1, "b": 2}) == version_token({"b": 2, "a": 1})


def test_two_different_states_get_two_different_tokens() -> None:
    assert version_token("summary", "base") != version_token("summary", "best")


def test_none_is_distinguishable_from_the_string_none() -> None:
    """A date filter that is absent is not a date filter set to the word None."""
    assert version_token(None) != version_token("None")


def test_a_changed_response_shape_changes_the_validator() -> None:
    """The failure this closes is quiet: a deploy renames a field, the data has
    not moved, so every browser is told 304 and renders last week's shape."""
    from pydantic import BaseModel

    class Before(BaseModel):
        total: float

    class After(BaseModel):
        total: float
        currency: str

    assert shape_token(Before) != shape_token(After)


def test_if_none_match_uses_the_weak_comparison() -> None:
    """`W/"x"` and `"x"` are the same entity for a conditional GET."""
    tag = etag_for("abc")

    assert matches(tag, tag) is True
    assert matches('"abc"', tag) is True
    assert matches("*", tag) is True
    assert matches('W/"something-else"', tag) is False
    assert matches(None, tag) is False
    assert matches('W/"other", W/"abc"', tag) is True


# ---- the endpoints --------------------------------------------------------


@pytest.mark.parametrize("path", READS)
async def test_a_read_offers_a_validator(client: AsyncClient, path: str) -> None:
    await _seed_and_run(client)

    response = await client.get(path)

    assert response.status_code == 200
    assert response.headers["ETag"].startswith('W/"')
    # `no-cache` does not mean "do not store" — it means "store it, and ask
    # before using it". A max-age would let a browser show a figure from
    # before somebody rescored the run.
    assert response.headers["Cache-Control"] == "private, no-cache"


@pytest.mark.parametrize("path", READS)
async def test_an_unchanged_read_is_answered_304_with_no_body(
    client: AsyncClient, path: str
) -> None:
    await _seed_and_run(client)
    first = await client.get(path)

    again = await client.get(path, headers={"If-None-Match": first.headers["ETag"]})

    assert again.status_code == 304
    assert again.content == b""
    # The client is updating a stored entry from this answer. One that arrived
    # without validators could never be revalidated again.
    assert again.headers["ETag"] == first.headers["ETag"]
    assert again.headers["Cache-Control"] == "private, no-cache"


async def test_a_stale_validator_gets_the_whole_answer(client: AsyncClient) -> None:
    await _seed_and_run(client)

    response = await client.get(
        "/api/dashboard/summary", headers={"If-None-Match": 'W/"not-this-one"'}
    )

    assert response.status_code == 200
    assert response.json()["has_data"] is True


async def test_each_scenario_view_has_its_own_validator(client: AsyncClient) -> None:
    """The base and worst cases are different numbers under one URL path."""
    await _seed_and_run(client)

    base = await client.get("/api/dashboard/summary?view=base")
    worst = await client.get("/api/dashboard/summary?view=worst")

    assert base.headers["ETag"] != worst.headers["ETag"]

    crossed = await client.get(
        "/api/dashboard/summary?view=worst", headers={"If-None-Match": base.headers["ETag"]}
    )
    assert crossed.status_code == 200


async def test_a_breakdown_column_is_part_of_the_validator(client: AsyncClient) -> None:
    """Serving the region split to somebody who asked for the category one is
    the classic way a cache goes wrong."""
    await _seed_and_run(client)

    region = await client.get("/api/dashboard/breakdown", params={"column": "region"})
    category = await client.get("/api/dashboard/breakdown", params={"column": "product_category"})

    assert region.status_code == category.status_code == 200
    assert region.headers["ETag"] != category.headers["ETag"]

    crossed = await client.get(
        "/api/dashboard/breakdown",
        params={"column": "product_category"},
        headers={"If-None-Match": region.headers["ETag"]},
    )
    assert crossed.status_code == 200
    assert crossed.json()["column"] == "product_category"


async def test_a_date_range_is_part_of_the_validator(client: AsyncClient) -> None:
    await _seed_and_run(client)

    everything = await client.get("/api/dashboard/summary")
    narrowed = await client.get("/api/dashboard/summary?start=2026-01-01&end=2026-03-01")

    assert everything.headers["ETag"] != narrowed.headers["ETag"]


async def test_rewriting_the_insights_changes_their_validator(
    client: AsyncClient, monkeypatch
) -> None:
    """The one dependency the run row alone would miss.

    Rewriting insights through a model changes what /insights answers without
    touching `forecast_runs` at all, so the version has to reach into the
    insights' own high-water mark. Without that, somebody who has just paid a
    provider to reword their insights keeps being told 304.
    """
    await _seed_and_run(client)
    before = await client.get("/api/insights")

    def stub(source: str, config: dict[str, object] | None = None) -> LlmCallResult:
        title, explanation, action = [*source.split("\n"), "", "", ""][:3]
        return LlmCallResult(
            text=f"Reworded: {title}\n{explanation}\n{action}",
            usage=LlmUsageRecord(provider="stub", model="stub-1", status="success", latency_ms=1.0),
        )

    monkeypatch.setattr("app.insights.llm._call_llm_api", stub)
    rewritten = await client.post(
        "/api/insights/rewrite", json={"llm_api_key": "k", "llm_model": "stub-1"}
    )
    assert rewritten.json()["rewritten"] > 0

    after = await client.get("/api/insights", headers={"If-None-Match": before.headers["ETag"]})

    assert after.status_code == 200
    assert after.headers["ETag"] != before.headers["ETag"]
    assert all(item["title"].startswith("Reworded: ") for item in after.json()["items"])


async def test_a_second_read_is_served_from_the_cache(client: AsyncClient) -> None:
    await _seed_and_run(client)
    cache.dashboard_cache.reset_stats()

    await client.get("/api/dashboard/summary")
    await client.get("/api/dashboard/summary")

    assert cache.dashboard_cache.stats.misses == 1
    assert cache.dashboard_cache.stats.hits == 1


async def test_deleting_a_run_reclaims_its_cached_answers(client: AsyncClient) -> None:
    run = await _seed_and_run(client)
    await client.get("/api/dashboard/summary")
    assert cache.dashboard_cache.stats.entries > 0

    deleted = await client.delete(f"/api/forecasts/{run['id']}")

    assert deleted.status_code in (200, 204)
    assert cache.dashboard_cache.stats.entries == 0


async def test_a_deployment_with_no_runs_is_not_cached(client: AsyncClient) -> None:
    """The "no data yet" answer is cheap, and caching it would make the first
    forecast a deployment ever runs look like it produced nothing."""
    response = await client.get("/api/dashboard/summary")

    assert response.status_code == 200
    assert response.json()["has_data"] is False
    assert cache.dashboard_cache.stats.entries == 0


async def test_the_cache_can_be_switched_off_without_losing_the_validator(
    client: AsyncClient, monkeypatch
) -> None:
    """Two independent mechanisms. Turning the memory off must not turn the
    conditional handshake off with it."""
    from app.core.config import settings

    await _seed_and_run(client)
    monkeypatch.setattr(settings, "dashboard_cache_enabled", False)
    cache.clear_all()

    first = await client.get("/api/dashboard/summary")
    again = await client.get(
        "/api/dashboard/summary", headers={"If-None-Match": first.headers["ETag"]}
    )

    assert again.status_code == 304
    assert cache.dashboard_cache.stats.entries == 0


async def test_a_conditional_answer_is_counted(client: AsyncClient) -> None:
    from app.core import metrics

    await _seed_and_run(client)
    first = await client.get("/api/dashboard/summary")
    await client.get("/api/dashboard/summary", headers={"If-None-Match": first.headers["ETag"]})

    assert (
        metrics.conditional_responses.value(route="/api/dashboard/summary", outcome="not_modified")
        == 1.0
    )
