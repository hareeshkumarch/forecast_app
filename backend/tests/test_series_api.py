"""
The triage endpoint: which series a planner should look at first.

A grouped run can hold hundreds of series, and the list is only useful if it
can be ordered by something that answers that question. These check the
ordering, the paging, and that a series without a measured error cannot elbow
its way to the top of a list it has no evidence to be in.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.database.sample_data import generate_csv_bytes

GRAIN = ["region", "product_category"]


async def _grouped_run(client: AsyncClient, grain: list[str] | None = None) -> dict:
    upload = await client.post(
        "/api/datasets/upload",
        files={"file": ("panel.csv", generate_csv_bytes(), "text/csv")},
    )
    assert upload.status_code == 201, upload.text

    body: dict = {
        "dataset_id": upload.json()["dataset"]["id"],
        "horizon": 3,
        "max_folds": 1,
    }
    if grain is not None:
        body["group_by"] = grain

    run = await client.post("/api/forecasts/run", json=body)
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]

    async with client.stream("GET", f"/api/forecasts/{run_id}/events") as stream:
        async for _ in stream.aiter_lines():
            pass

    detail = await client.get(f"/api/forecasts/{run_id}")
    assert detail.json()["status"] == "completed", detail.json().get("error_message")
    return detail.json()


async def test_a_grouped_run_lists_its_series_worst_first(client: AsyncClient) -> None:
    run = await _grouped_run(client, GRAIN)

    assert run["group_by"] == GRAIN
    assert run["series_count"] > 0

    response = await client.get(f"/api/forecasts/{run['id']}/series", params={"limit": 100})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["group_by"] == GRAIN
    assert body["sort"] == "value_at_risk"
    assert body["total"] == run["series_count"]

    rows = body["rows"]
    assert len(rows) == body["total"]
    assert {row["level"] for row in rows} == {0, 1, 2}

    # Value at risk is what the default order means, and it has to be ordered.
    at_risk = [row["value_at_risk"] for row in rows if row["value_at_risk"] is not None]
    assert at_risk == sorted(at_risk, reverse=True), at_risk

    # It is also the thing neither error nor size says on its own.
    for row in rows:
        if row["wmape"] is None:
            assert row["value_at_risk"] is None
        else:
            assert row["value_at_risk"] == pytest.approx(
                abs(row["forecast_total"]) * row["wmape"] / 100.0, rel=1e-6
            )


async def test_a_series_without_a_measured_error_sorts_last(client: AsyncClient) -> None:
    run = await _grouped_run(client, GRAIN)

    response = await client.get(f"/api/forecasts/{run['id']}/series", params={"limit": 200})
    rows = response.json()["rows"]

    measured = [index for index, row in enumerate(rows) if row["wmape"] is not None]
    unmeasured = [index for index, row in enumerate(rows) if row["wmape"] is None]

    if measured and unmeasured:
        assert max(measured) < min(unmeasured), "an unknown risk is not evidence of a large one"


async def test_the_trend_compares_two_windows_of_the_same_length(client: AsyncClient) -> None:
    run = await _grouped_run(client, GRAIN)

    rows = (await client.get(f"/api/forecasts/{run['id']}/series", params={"limit": 200})).json()[
        "rows"
    ]

    trends = [row["change_vs_prior"] for row in rows if row["change_vs_prior"] is not None]
    assert trends, "the sample data has enough history to trend"

    # The forecast covers three periods and a window covers twelve, so comparing
    # them would read as a collapse of roughly two thirds on every single row.
    assert not all(trend < -40 for trend in trends), trends[:5]

    for row in rows:
        if row["prior_total"]:
            assert row["change_vs_prior"] == pytest.approx(
                (row["current_total"] - row["prior_total"]) / abs(row["prior_total"]) * 100.0,
                abs=0.01,  # the percentage is reported to two decimals
            )

    # A parent has no series of its own, so its history is its children's.
    parents = {row["id"]: row for row in rows if row["level"] < 2}
    for parent_id, parent in parents.items():
        children = [row for row in rows if row["parent_id"] == parent_id]
        if children:
            assert sum(child["current_total"] for child in children) == pytest.approx(
                parent["current_total"], rel=1e-6
            )


async def test_the_list_can_be_narrowed_to_a_level_and_a_parent(client: AsyncClient) -> None:
    run = await _grouped_run(client, GRAIN)
    run_id = run["id"]

    regions = (
        await client.get(f"/api/forecasts/{run_id}/series", params={"level": 1, "limit": 100})
    ).json()
    assert regions["total"] == 5, "five regions"
    assert all(row["level"] == 1 for row in regions["rows"])

    parent = regions["rows"][0]
    children = (
        await client.get(
            f"/api/forecasts/{run_id}/series",
            params={"parent_id": parent["id"], "limit": 100},
        )
    ).json()

    assert children["total"] == 5, "five categories under a region"
    assert all(row["parent_id"] == parent["id"] for row in children["rows"])
    assert sum(row["forecast_total"] for row in children["rows"]) == pytest.approx(
        parent["forecast_total"], rel=1e-6
    )


async def test_the_list_pages_and_searches(client: AsyncClient) -> None:
    run = await _grouped_run(client, GRAIN)
    run_id = run["id"]

    first = (
        await client.get(f"/api/forecasts/{run_id}/series", params={"limit": 4, "offset": 0})
    ).json()
    second = (
        await client.get(f"/api/forecasts/{run_id}/series", params={"limit": 4, "offset": 4})
    ).json()

    assert len(first["rows"]) == 4
    assert first["has_more"] is True
    assert {row["id"] for row in first["rows"]}.isdisjoint({row["id"] for row in second["rows"]})

    found = (
        await client.get(f"/api/forecasts/{run_id}/series", params={"search": "Europe"})
    ).json()
    assert found["total"] > 0
    assert all("Europe" in row["label"] for row in found["rows"])


async def test_a_series_scopes_the_points_to_its_own_curve(client: AsyncClient) -> None:
    run = await _grouped_run(client, GRAIN)
    run_id = run["id"]

    leaf = (
        await client.get(f"/api/forecasts/{run_id}/series", params={"level": 2, "limit": 1})
    ).json()["rows"][0]

    headline = (await client.get(f"/api/forecasts/{run_id}/points")).json()
    scoped = (
        await client.get(f"/api/forecasts/{run_id}/points", params={"series_id": leaf["id"]})
    ).json()

    assert headline["points"], "the run keeps its own top line"
    assert scoped["points"], "a series has a curve of its own"

    # Its own past as well as its horizon, on the same calendar as the top
    # line: a chart scoped to one series would otherwise be a handful of
    # forecast points hanging on nothing.
    assert scoped["boundary_index"] == headline["boundary_index"]
    assert [p["period"] for p in scoped["points"]] == [p["period"] for p in headline["points"]]

    history = [p for p in scoped["points"] if p["kind"] == "actual"]
    assert history and all(p["actual"] is not None for p in history)
    assert sum(p["actual"] for p in history) < sum(
        p["actual"] for p in headline["points"] if p["kind"] == "actual"
    ), "one series is a part of the whole, not the whole"

    total = sum(point["forecast"] or 0.0 for point in scoped["points"])
    assert total == pytest.approx(leaf["forecast_total"], rel=1e-6)


async def test_exporting_a_grouped_run_says_which_series_each_row_is(client: AsyncClient) -> None:
    """
    A grouped run stores a curve per series as well as its own line. Flattened
    without a label they export as dozens of identical-looking rows per period,
    which is a tree with the tree left out.
    """
    run = await _grouped_run(client, GRAIN)

    csv = (await client.get(f"/api/exports/{run['id']}?format=csv")).text
    header, *lines = csv.strip().splitlines()

    assert header.startswith("series,period,kind"), header
    labels = {line.split(",", 1)[0] for line in lines}
    assert "Total" in labels, "the run's own line is named rather than left blank"

    # Every series below the root, plus "Total" standing in for the root —
    # whose own curve is not stored, being the top line already.
    assert len(labels) == run["series_count"], sorted(labels)[:5]
    assert "Europe · Product A" in labels
    assert "Europe" in labels, "the levels between the total and the grain are exported too"

    # The PDF reports the top line and ranks the series; it must not print the
    # whole tree as one undifferentiated column of dates.
    pdf = (await client.get(f"/api/exports/{run['id']}?format=pdf")).content
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")


async def test_a_run_without_a_grain_has_no_series(client: AsyncClient) -> None:
    run = await _grouped_run(client)

    assert run["group_by"] == []
    assert run["series_count"] == 0

    body = (await client.get(f"/api/forecasts/{run['id']}/series")).json()
    assert body["total"] == 0
    assert body["rows"] == []
    assert body["has_more"] is False


@pytest.mark.parametrize(
    ("grain", "reason"),
    [
        (["not_a_column"], "unknown column"),
        (["region", "region"], "the same column twice"),
        (["order_date"], "the time column"),
        (["revenue"], "the target column"),
    ],
)
async def test_a_bad_grain_is_refused_before_the_run_starts(
    client: AsyncClient, grain: list[str], reason: str
) -> None:
    upload = await client.post(
        "/api/datasets/upload",
        files={"file": ("panel.csv", generate_csv_bytes(), "text/csv")},
    )
    dataset_id = upload.json()["dataset"]["id"]

    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": dataset_id, "group_by": grain, "horizon": 3},
    )

    assert response.status_code in (400, 422), f"{reason}: {response.text}"


async def test_every_offered_order_actually_answers(client: AsyncClient) -> None:
    """Each sort the UI offers returns rows, in that order, without erroring.

    `label` is the one that mattered. Its ORDER BY carried a literal `NULL` as
    a stand-in for the "unscored last" term the other orders use, which SQLite
    accepts and Postgres rejects outright — so the name order was a 500 in
    production and a pass in this suite, which runs on SQLite. The compiled-SQL
    check below is the part that would have caught it; this one is here because
    an endpoint should be asked for what the interface can ask it for.
    """
    run = await _grouped_run(client, GRAIN)

    for sort in ("value_at_risk", "wmape", "forecast_total", "label"):
        response = await client.get(
            f"/api/forecasts/{run['id']}/series", params={"sort": sort, "limit": 50}
        )
        assert response.status_code == 200, f"{sort}: {response.text}"
        body = response.json()
        assert body["sort"] == sort
        assert body["rows"], f"{sort} returned nothing"

    by_name = (
        await client.get(
            f"/api/forecasts/{run['id']}/series", params={"sort": "label", "limit": 50}
        )
    ).json()["rows"]
    labels = [row["label"] for row in by_name]
    assert labels == sorted(labels), labels


def test_no_order_asks_the_database_to_sort_by_a_constant() -> None:
    """The name order compiled to `ORDER BY NULL`, which only Postgres refuses.

    Compiled from `series_service.order_terms` itself, against the dialect the
    product runs on rather than the one this suite runs on. A term that is a
    bare constant can never order anything, so finding one is finding a bug
    whichever database is asked to execute it.
    """
    import uuid as _uuid

    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.models.entities import ForecastSeries
    from app.services import series_service

    for sort in series_service.SORTS:
        statement = (
            select(ForecastSeries)
            .where(ForecastSeries.run_id == _uuid.uuid4())
            .order_by(*series_service.order_terms(sort))
        )
        clause = str(statement.compile(dialect=postgresql.dialect())).split("ORDER BY", 1)[1]

        for term in clause.split(","):
            bare = term.strip().removesuffix(" ASC").removesuffix(" DESC").strip()
            assert bare.upper() != "NULL", f"{sort} orders by a constant: {clause.strip()}"
