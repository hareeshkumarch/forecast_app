from __future__ import annotations

import json
import math
import uuid
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from dateutil.relativedelta import relativedelta
from httpx import AsyncClient

from app.connectors.registry import ADAPTERS, RAIL_ORDER
from app.database.sample_data import generate_csv_bytes
from app.database.seed import seed_connectors
from app.database.session import session_scope
from app.insights.llm import LlmCallResult, LlmUsageRecord
from app.models.enums import ModelKind
from app.services import dataset_service, forecast_service


async def _seed_and_run(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/datasets/upload",
        files={"file": ("sample.csv", generate_csv_bytes(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    dataset = response.json()["dataset"]

    run = await client.post(
        "/api/forecasts/run",
        json={
            "dataset_id": dataset["id"],
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


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["storage_writable"] is True
    assert body["max_upload_mb"] == 20.0


async def test_seeded_connectors_are_listed_in_rail_order(client: AsyncClient) -> None:
    await seed_connectors()

    response = await client.get("/api/connectors")
    assert response.status_code == 200

    connectors = response.json()
    assert len(connectors) == 10
    assert [c["name"] for c in connectors][:3] == ["BigQuery", "Snowflake", "Amazon Redshift"]

    assert all(c["status"] == "not_configured" for c in connectors)


async def test_connector_create_never_returns_credentials(client: AsyncClient) -> None:
    response = await client.post(
        "/api/connectors",
        json={
            "name": "Warehouse",
            "type": "postgresql",
            "config": {"host": "db.example.com", "port": 5432, "database": "analytics"},
            "credentials": {"username": "reader", "password": "super-secret-value"},
        },
    )
    assert response.status_code == 201

    body = response.json()
    serialised = response.text
    assert "super-secret-value" not in serialised
    assert "reader" not in serialised

    assert sorted(body["credential_keys"]) == ["password", "username"]
    assert "password" not in body["config"]


async def test_duplicate_connector_name_is_rejected(client: AsyncClient) -> None:
    payload = {"name": "Dup", "type": "mysql", "config": {}, "credentials": {}}
    assert (await client.post("/api/connectors", json=payload)).status_code == 201

    conflict = await client.post("/api/connectors", json=payload)
    assert conflict.status_code == 422
    assert "already exists" in conflict.json()["error"]["message"]


async def test_connector_types_drive_the_modal(client: AsyncClient) -> None:
    response = await client.get("/api/connectors/types")
    assert response.status_code == 200

    types = response.json()

    # Every connector offered in the rail must reach the modal, so adding one
    # cannot silently leave it unconfigurable. CSV is deliberately absent —
    # files arrive through upload, not through a connection.
    assert {item["type"] for item in types} == {kind.value for kind in RAIL_ORDER}
    assert set(RAIL_ORDER) <= set(ADAPTERS), "a rail entry with no adapter would 500"
    assert all(item["fields"] for item in types), "a type with no fields cannot be configured"

    bigquery = next(item for item in types if item["type"] == "bigquery")
    assert any(field["secret"] for field in bigquery["fields"])

    supabase = next(item for item in types if item["type"] == "supabase")
    assert supabase["supports_import"] is True
    assert {field["key"] for field in supabase["fields"]} >= {"project_ref", "password"}


async def test_a_run_past_the_first_page_is_still_reachable(client: AsyncClient) -> None:
    """
    The list used to stop at fifty with no way to ask for the fifty-first.

    Nothing said so: a workspace of forty-seven runs and a workspace of five
    hundred looked identical, and the screen's own counter reported the cap as
    though it were the truth.
    """
    upload = await client.post(
        "/api/datasets/upload",
        files={"file": ("sample.csv", generate_csv_bytes(), "text/csv")},
    )
    dataset_id = upload.json()["dataset"]["id"]

    async with session_scope() as session:
        for index in range(7):
            await forecast_service.create_run(
                session,
                dataset_id=uuid.UUID(dataset_id),
                name=f"Run {index:02d}",
                horizon=2,
                max_folds=1,
            )
        await session.commit()

    first = (await client.get("/api/forecasts", params={"limit": 3})).json()
    assert len(first["rows"]) == 3
    assert first["total"] == 7, "the total counts what exists, not what was sent"
    assert first["counts"]["all"] == 7

    second = (await client.get("/api/forecasts", params={"limit": 3, "offset": 3})).json()
    assert len(second["rows"]) == 3
    assert {row["id"] for row in second["rows"]}.isdisjoint({row["id"] for row in first["rows"]})

    last = (await client.get("/api/forecasts", params={"limit": 3, "offset": 6})).json()
    assert len(last["rows"]) == 1

    seen = {row["name"] for page in (first, second, last) for row in page["rows"]}
    assert seen == {f"Run {index:02d}" for index in range(7)}


async def test_searching_runs_reaches_past_the_page_in_the_browser(client: AsyncClient) -> None:
    """Searching a truncated list reported that older runs did not exist."""
    upload = await client.post(
        "/api/datasets/upload",
        files={"file": ("sample.csv", generate_csv_bytes(), "text/csv")},
    )
    dataset_id = upload.json()["dataset"]["id"]

    async with session_scope() as session:
        await forecast_service.create_run(
            session, dataset_id=uuid.UUID(dataset_id), name="Needle", horizon=2, max_folds=1
        )
        for index in range(5):
            await forecast_service.create_run(
                session,
                dataset_id=uuid.UUID(dataset_id),
                name=f"Haystack {index}",
                horizon=2,
                max_folds=1,
            )
        await session.commit()

    # Oldest first, so "Needle" sits outside a one-row page.
    page = (await client.get("/api/forecasts", params={"limit": 1})).json()
    assert page["rows"][0]["name"] != "Needle"

    found = (await client.get("/api/forecasts", params={"limit": 1, "search": "needle"})).json()
    assert found["total"] == 1
    assert found["rows"][0]["name"] == "Needle"

    # And the counters describe the search rather than the whole workspace.
    assert found["counts"]["all"] == 1


async def test_the_data_screen_s_totals_are_over_everything_held(client: AsyncClient) -> None:
    for index in range(4):
        await client.post(
            "/api/datasets/upload",
            files={"file": (f"file-{index}.csv", generate_csv_bytes(), "text/csv")},
        )

    page = (await client.get("/api/datasets", params={"limit": 2})).json()

    assert len(page["rows"]) == 2, "a page"
    assert page["total"] == 4, "of four"
    assert page["ready"] == 4
    # The figures the screen reports above the table answer "how much data do
    # we hold", which the two rows on screen cannot.
    assert page["row_count"] == sum(row["row_count"] for row in page["rows"]) * 2
    assert page["file_size_bytes"] > sum(row["file_size_bytes"] for row in page["rows"])


async def test_deleting_a_dataset_reclaims_the_files_it_owned(client: AsyncClient) -> None:
    """
    The row went and the bytes stayed.

    Nothing else knew those files existed once the row naming them was gone, so
    every delete leaked an upload and a parquet for ever — and the screen that
    offers the delete reports how much disk the uploads take up.
    """
    upload = await client.post(
        "/api/datasets/upload",
        files={"file": ("throwaway.csv", generate_csv_bytes(), "text/csv")},
    )
    dataset_id = upload.json()["dataset"]["id"]

    async with session_scope() as session:
        dataset = await dataset_service.get_dataset(session, uuid.UUID(dataset_id))
        files = [Path(path) for path in (dataset.parquet_path, dataset.raw_path) if path]

    assert files, "an upload writes at least one file"
    assert all(path.exists() for path in files)

    assert (await client.delete(f"/api/datasets/{dataset_id}")).status_code == 204

    assert not any(path.exists() for path in files), "deleting the row leaves the bytes behind"
    assert (await client.get(f"/api/datasets/{dataset_id}")).status_code == 404


async def test_a_connector_can_be_corrected_after_it_is_saved(client: AsyncClient) -> None:
    """
    A wrong host or a rotated password used to be permanent.

    The route to fix it existed and nothing called it, so the only way out was
    a second connector with a slightly different name.
    """
    created = await client.post(
        "/api/connectors",
        json={
            "name": "Warehouse",
            "type": "postgresql",
            "config": {"host": "wrong.example.com", "port": 5432, "database": "analytics"},
            "credentials": {"username": "reader", "password": "old-secret"},
        },
    )
    connector_id = created.json()["id"]

    response = await client.patch(
        f"/api/connectors/{connector_id}",
        json={
            "name": "Warehouse (EU)",
            "config": {"host": "right.example.com", "port": 5432, "database": "analytics"},
            "credentials": {"username": "reader", "password": "new-secret"},
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["name"] == "Warehouse (EU)"
    assert body["config"]["host"] == "right.example.com"
    assert "new-secret" not in response.text, "a correction must not echo the new password back"
    assert sorted(body["credential_keys"]) == ["password", "username"]


async def test_deleting_a_connector_keeps_what_was_imported_through_it(
    client: AsyncClient,
) -> None:
    """
    Retiring a connection is not a reason to lose the data that came through it.

    Once a table has landed it is a dataset like any other, with forecasts
    built on it, so the connector goes and the dataset stays.
    """
    created = await client.post(
        "/api/connectors",
        json={
            "name": "Retire me",
            "type": "postgresql",
            "config": {"host": "db.example.com", "port": 5432, "database": "analytics"},
            "credentials": {"username": "reader", "password": "secret"},
        },
    )
    connector_id = created.json()["id"]

    upload = await client.post(
        "/api/datasets/upload",
        files={"file": ("through-the-connector.csv", generate_csv_bytes(), "text/csv")},
    )
    dataset_id = upload.json()["dataset"]["id"]

    assert (await client.delete(f"/api/connectors/{connector_id}")).status_code == 204
    assert (await client.get(f"/api/connectors/{connector_id}")).status_code == 404
    assert (await client.get(f"/api/datasets/{dataset_id}")).status_code == 200

    # And a second delete says so rather than pretending it worked.
    assert (await client.delete(f"/api/connectors/{connector_id}")).status_code == 404


async def test_test_endpoint_reports_not_configured(client: AsyncClient) -> None:
    response = await client.post("/api/connectors/test", json={"type": "postgresql"})
    assert response.status_code == 200

    body = response.json()
    assert body["ok"] is False
    assert body["status"] == "not_configured"


async def test_upload_profiles_and_returns_suggestions(client: AsyncClient) -> None:
    response = await client.post(
        "/api/datasets/upload",
        files={"file": ("sample.csv", generate_csv_bytes(), "text/csv")},
    )
    assert response.status_code == 201

    body = response.json()
    dataset, profile = body["dataset"], body["profile"]

    assert dataset["row_count"] == 1050
    assert dataset["column_count"] == 5
    assert dataset["frequency"] == "monthly"
    assert dataset["time_column"] == "order_date"
    assert dataset["target_column"] == "revenue"

    assert profile["time_column_suggestions"][0]["name"] == "order_date"
    assert profile["target_column_suggestions"][0]["name"] == "revenue"
    assert {s["name"] for s in profile["dimension_suggestions"]} == {"region", "product_category"}
    assert len(profile["preview_rows"]) > 0


@pytest.mark.parametrize(
    ("filename", "content", "status"),
    [
        ("bad.pdf", b"%PDF-1.4", 415),
        ("empty.csv", b"", 422),
        ("headers.csv", b"a,b,c\n", 422),
    ],
)
async def test_upload_rejections(
    client: AsyncClient, filename: str, content: bytes, status: int
) -> None:
    response = await client.post(
        "/api/datasets/upload", files={"file": (filename, content, "application/octet-stream")}
    )
    assert response.status_code == status
    assert response.json()["error"]["message"]


async def test_configure_rejects_unknown_column(client: AsyncClient) -> None:
    upload = await client.post(
        "/api/datasets/upload", files={"file": ("s.csv", generate_csv_bytes(), "text/csv")}
    )
    dataset_id = upload.json()["dataset"]["id"]

    response = await client.patch(
        f"/api/datasets/{dataset_id}",
        json={
            "time_column": "order_date",
            "target_column": "does_not_exist",
            "frequency": "monthly",
            "horizon": 6,
        },
    )
    assert response.status_code == 422
    assert "not a column" in response.json()["error"]["message"]


async def test_configure_rejects_identical_columns(client: AsyncClient) -> None:
    upload = await client.post(
        "/api/datasets/upload", files={"file": ("s.csv", generate_csv_bytes(), "text/csv")}
    )
    dataset_id = upload.json()["dataset"]["id"]

    response = await client.patch(
        f"/api/datasets/{dataset_id}",
        json={
            "time_column": "revenue",
            "target_column": "revenue",
            "frequency": "monthly",
            "horizon": 6,
        },
    )
    assert response.status_code == 422


async def test_forecast_run_completes_and_selects_a_model(client: AsyncClient) -> None:
    run = await _seed_and_run(client)

    assert run["selected_model"] in {kind.value for kind in ModelKind}
    assert run["selection_rationale"]
    assert run["progress"] == 1.0
    assert run["forecast_start"] and run["forecast_end"]


async def test_metrics_expose_every_candidate_and_the_scoring_rule(client: AsyncClient) -> None:
    run = await _seed_and_run(client)

    response = await client.get(f"/api/forecasts/{run['id']}/metrics")
    assert response.status_code == 200

    body = response.json()
    assert "norm(wMAPE)" in body["scoring_rule"]
    assert {c["model"] for c in body["candidates"]} <= {kind.value for kind in ModelKind}
    assert len(body["candidates"]) >= 6
    assert sum(1 for c in body["candidates"] if c["selected"]) == 1

    metrics = {m["name"] for m in body["metrics"]}
    assert {"mae", "rmse", "smape", "wmape", "accuracy"} <= metrics


async def test_points_carry_bounds_and_a_boundary(client: AsyncClient) -> None:
    run = await _seed_and_run(client)

    response = await client.get(f"/api/forecasts/{run['id']}/points")
    body = response.json()

    assert body["boundary_index"] is not None
    forecast_points = body["points"][body["boundary_index"] :]
    assert len(forecast_points) == 6

    for point in forecast_points:
        assert point["lower_bound"] <= point["forecast"] <= point["upper_bound"]
        assert point["worst_case"] <= point["base_case"] <= point["best_case"]


async def test_run_on_missing_dataset_is_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/forecasts/run", json={"dataset_id": str(uuid.uuid4()), "horizon": 6}
    )
    assert response.status_code == 404


async def test_dashboard_summary_returns_six_kpis(client: AsyncClient) -> None:
    await _seed_and_run(client)

    response = await client.get("/api/dashboard/summary")
    body = response.json()

    assert body["has_data"] is True
    assert [kpi["key"] for kpi in body["kpis"]] == [
        "total_forecast",
        "actual_ytd",
        "forecast_accuracy",
        "weighted_mape",
        "best_case",
        "worst_case",
    ]
    assert all(kpi["display_value"] != "" for kpi in body["kpis"])


async def test_a_first_run_does_not_caption_a_comparison_it_never_made(
    client: AsyncClient,
) -> None:
    """A caption naming a comparison with no number beside it reads as a broken card.

    On a first run there is no previous run, so three of the six cards used to
    print a bare "vs previous run" under the value and nothing else.
    """
    await _seed_and_run(client)

    body = (await client.get("/api/dashboard/summary")).json()

    for kpi in body["kpis"]:
        label = kpi["comparison_label"]
        if label is None or not label.startswith("vs "):
            continue
        assert (
            kpi["delta_display"] is not None
        ), f"{kpi['key']} says {label!r} with nothing to compare against"

    # The window caption under Actual YTD is not a comparison and stands alone.
    actual = next(kpi for kpi in body["kpis"] if kpi["key"] == "actual_ytd")
    assert actual["comparison_label"], "the actual window is worth stating on its own"


async def test_dashboard_is_empty_before_any_run(client: AsyncClient) -> None:
    response = await client.get("/api/dashboard/summary")
    body = response.json()

    assert body["has_data"] is False
    assert body["kpis"] == []
    assert body["run_id"] is None


async def test_scenario_view_changes_the_totals(client: AsyncClient) -> None:
    await _seed_and_run(client)

    async def total(view: str) -> float:
        response = await client.get(f"/api/dashboard/summary?view={view}")
        return response.json()["kpis"][0]["value"]

    worst, base, best = await total("worst"), await total("base"), await total("best")
    assert worst < base < best


async def test_invalid_view_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/dashboard/summary?view=bogus")
    assert response.status_code == 422
    assert "not a valid forecast view" in response.json()["error"]["message"]


async def test_inverted_date_range_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/dashboard/summary?start=2026-06-01&end=2026-01-01")
    assert response.status_code == 422
    assert "after the end date" in response.json()["error"]["message"]


async def test_breakdowns_come_from_the_run_and_add_up(client: AsyncClient) -> None:
    """
    The splits are whatever columns this run actually has, so the test asks the
    summary which ones exist rather than assuming a region and a category.
    """
    await _seed_and_run(client)

    summary = (await client.get("/api/dashboard/summary")).json()
    offered = summary["breakdowns"]
    assert offered, "a run with dimensions should offer at least one split"

    for reference in offered:
        breakdown = (
            await client.get("/api/dashboard/breakdown", params={"column": reference["column"]})
        ).json()

        assert breakdown["label"] == reference["label"]
        assert breakdown["rows"]
        assert sum(row["forecast"] for row in breakdown["rows"]) == pytest.approx(
            breakdown["total"], rel=1e-6
        )
        assert sum(row["share"] for row in breakdown["rows"]) == pytest.approx(100.0, abs=0.1)


async def test_drivers_are_ranked(client: AsyncClient) -> None:
    await _seed_and_run(client)

    drivers = (await client.get("/api/dashboard/drivers")).json()

    assert len(drivers["rows"]) == 5
    assert [row["rank"] for row in drivers["rows"]] == sorted(
        row["rank"] for row in drivers["rows"]
    )


async def test_insights_are_generated_from_the_run(client: AsyncClient) -> None:
    await _seed_and_run(client)

    response = await client.get("/api/insights")
    items = response.json()["items"]

    assert len(items) > 0
    for insight in items:
        assert insight["title"]
        assert insight["explanation"]
        assert insight["suggested_action"]
        assert insight["metric_name"]
        assert insight["generated_at"]
        assert insight["severity"] in {"positive", "info", "warning", "critical"}


async def test_insights_can_be_reworded_and_put_back(client: AsyncClient, monkeypatch) -> None:
    """
    The rewriter has to work against a finished run: a key added afterwards is
    worth nothing if applying it means refitting every model again.
    """
    await _seed_and_run(client)

    def stub(source: str, config: dict[str, object] | None = None) -> LlmCallResult:
        title, explanation, action = [*source.split("\n"), "", "", ""][:3]
        return LlmCallResult(
            text=f"Reworded: {title}\n{explanation}\n{action}",
            usage=LlmUsageRecord(provider="stub", model="stub-1", status="success", latency_ms=1.0),
        )

    monkeypatch.setattr("app.insights.llm._call_llm_api", stub)

    computed = (await client.get("/api/insights")).json()["items"]

    rewritten = (
        await client.post("/api/insights/rewrite", json={"llm_api_key": "k", "llm_model": "stub-1"})
    ).json()

    assert rewritten["rewritten"] == rewritten["considered"] == len(computed)
    assert all(item["title"].startswith("Reworded: ") for item in rewritten["items"])
    assert all(item["llm_rewritten"] for item in rewritten["items"])

    # Twice over must not compound: the rewriter always starts from the
    # platform's own words, not from its own previous answer.
    again = (
        await client.post("/api/insights/rewrite", json={"llm_api_key": "k", "llm_model": "stub-1"})
    ).json()
    assert not any(item["title"].startswith("Reworded: Reworded: ") for item in again["items"])

    restored = (await client.post("/api/insights/plain")).json()
    assert [item["title"] for item in restored["items"]] == [item["title"] for item in computed]
    assert not any(item["llm_rewritten"] for item in restored["items"])


async def test_checking_a_provider_without_a_key_says_so(client: AsyncClient) -> None:
    response = await client.post("/api/insights/check", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error_code"] == "no_key"


@pytest.mark.parametrize(
    ("fmt", "magic", "media"),
    [
        ("csv", b"series,period,", "text/csv"),
        # A PDF that a reader will not open is worse than no PDF, so the file
        # is checked for what it claims to be rather than merely for bytes.
        ("pdf", b"%PDF-", "application/pdf"),
    ],
)
async def test_export_formats(client: AsyncClient, fmt: str, magic: bytes, media: str) -> None:
    run = await _seed_and_run(client)

    response = await client.get(f"/api/exports/{run['id']}?format={fmt}")
    assert response.status_code == 200
    assert response.content.startswith(magic), response.content[:40]
    assert media in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    assert f".{fmt}" in response.headers["content-disposition"]


async def test_a_retired_export_format_is_refused(client: AsyncClient) -> None:
    run = await _seed_and_run(client)

    response = await client.get(f"/api/exports/{run['id']}?format=xlsx")
    assert response.status_code == 422


async def test_the_pdf_report_carries_the_run_it_describes(client: AsyncClient) -> None:
    run = await _seed_and_run(client)

    response = await client.get(f"/api/exports/{run['id']}?format=pdf")
    body = response.content

    assert body.startswith(b"%PDF-")
    assert body.rstrip().endswith(b"%%EOF"), "a truncated PDF opens as a damaged file"
    # The title is metadata, so it survives compression of the page streams.
    assert run["name"].encode() in body
    assert len(body) > 2_000, "a report with no content would still be a valid PDF"


async def test_export_of_missing_run_is_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/exports/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.parametrize("prefix", ["datasets", "forecasts", "connectors"])
async def test_unknown_ids_return_404(client: AsyncClient, prefix: str) -> None:
    response = await client.get(f"/api/{prefix}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_a_finished_run_cannot_be_cancelled(client: AsyncClient) -> None:
    run = await _seed_and_run(client)

    response = await client.post(f"/api/forecasts/{run['id']}/cancel")

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert "already finished" in body["message"]


async def test_cancelling_an_unknown_run_is_a_clean_404(client: AsyncClient) -> None:
    response = await client.post(f"/api/forecasts/{uuid.uuid4()}/cancel")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_a_leading_column_in_the_upload_is_found_and_reported(client: AsyncClient) -> None:
    """
    End to end: a spare numeric column that genuinely leads the target should
    be picked up from the upload without anybody configuring anything, and the
    run should say so in words the reader can act on.
    """
    rng = np.random.default_rng(5)
    n, lag = 84, 6
    driver = rng.normal(0.0, 1.0, n)
    season = 200.0 + 40.0 * np.sin(2 * np.pi * np.arange(n) / 12.0)
    shock = np.zeros(n)
    shock[lag:] = 60.0 * driver[: n - lag]
    revenue = season + shock + rng.normal(0.0, 2.0, n)

    rows = ["order_date,revenue,web_sessions"]
    for index in range(n):
        period = date(2018, 1, 1) + relativedelta(months=index)
        rows.append(f"{period.isoformat()},{revenue[index]:.2f},{driver[index]:.4f}")

    upload = await client.post(
        "/api/datasets/upload",
        files={"file": ("leading.csv", "\n".join(rows).encode(), "text/csv")},
    )
    assert upload.status_code == 201, upload.text
    dataset = upload.json()["dataset"]

    run = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": dataset["id"], "horizon": lag},
    )
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]

    async with client.stream("GET", f"/api/forecasts/{run_id}/events") as stream:
        async for _ in stream.aiter_lines():
            pass

    metrics = (await client.get(f"/api/forecasts/{run_id}/metrics")).json()
    names = [column["name"] for column in metrics["leading_columns"]]

    assert names == ["web_sessions"]
    assert metrics["leading_columns"][0]["lag"] == lag
    assert "web_sessions from 6 months earlier" in metrics["selection_rationale"]


async def _forecast_csv(client: AsyncClient, name: str, rows: list[str], **run: object) -> dict:
    upload = await client.post(
        "/api/datasets/upload",
        files={"file": (f"{name}.csv", "\n".join(rows).encode(), "text/csv")},
    )
    assert upload.status_code == 201, upload.text

    started = await client.post(
        "/api/forecasts/run", json={"dataset_id": upload.json()["dataset"]["id"], **run}
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]

    async with client.stream("GET", f"/api/forecasts/{run_id}/events") as stream:
        async for _ in stream.aiter_lines():
            pass

    detail = await client.get(f"/api/forecasts/{run_id}")
    # The endpoint itself is the assertion: a metric that could not be measured
    # used to reach the response as a NaN, and `json.dumps` refuses those.
    assert detail.status_code == 200, detail.text
    return detail.json()


async def test_a_series_of_nothing_but_zeros_still_produces_a_forecast(
    client: AsyncClient,
) -> None:
    """
    A discontinued line, or one that has not launched yet. Every error measure
    divides by the series total, so the fits report an AICc of -Infinity — which
    Postgres rejects inside a JSON column, failing the whole run with a message
    naming a token nobody wrote.
    """
    rows = ["month,value"] + [
        f"{date(2021, 1, 1) + relativedelta(months=index):%Y-%m-%d},0" for index in range(36)
    ]

    detail = await _forecast_csv(client, "all_zero", rows, horizon=6)

    assert detail["status"] == "completed", detail.get("error_message")

    summary = (await client.get("/api/dashboard/summary", params={"run_id": detail["id"]})).json()
    shown = {kpi["key"]: kpi["display_value"] for kpi in summary["kpis"]}

    # Not measurable is shown as not measurable, never as a confident zero.
    assert shown["forecast_accuracy"] == "—"
    assert shown["weighted_mape"] == "—"

    # The invariant behind the fix, checked here because the suite runs on
    # SQLite and SQLite would happily store the -Infinity that Postgres throws
    # out. Every stored number has to be one a JSON column can hold.
    metrics = (await client.get(f"/api/forecasts/{detail['id']}/metrics")).json()
    for candidate in metrics["candidates"]:
        for name, value in candidate["params"].items():
            assert not isinstance(value, float) or math.isfinite(
                value
            ), f"{candidate['model']}.{name} is {value}, which Postgres will reject"
    assert json.dumps(metrics), "the metrics response must be serialisable"


async def test_a_dataset_too_short_to_backtest_still_answers_every_endpoint(
    client: AsyncClient,
) -> None:
    """
    Two rows leaves nothing to hold out, so every accuracy metric is NaN. Those
    reached the response untouched and turned `GET /forecasts/{id}` into a 500,
    which meant the run could not even be looked at, let alone deleted.
    """
    rows = ["month,value", "2024-01-01,10", "2024-02-01,12"]

    detail = await _forecast_csv(client, "two_rows", rows, horizon=1)
    run_id = detail["id"]

    for path in ("", "/metrics", "/points", "/series"):
        response = await client.get(f"/api/forecasts/{run_id}{path}")
        assert response.status_code == 200, f"{path or '(detail)'}: {response.text[:200]}"

    summary = await client.get("/api/dashboard/summary", params={"run_id": run_id})
    assert summary.status_code == 200
    assert all(
        kpi["display_value"] not in ("nan", "NaN", "inf", "") for kpi in summary.json()["kpis"]
    )


# ------------------------------------------------- refusing what cannot be run
#
# Every one of these used to be accepted and then quietly not done: a text
# column read as the target came back as a column of nulls, a driver that was
# not numeric was filtered out of the list without a word, a model roster that
# matched nothing fell back to running everything, and a horizon longer than
# the history produced a forecast whose accuracy had never been measured at
# that range. A run that says "completed" has to have done what it was asked.


async def _dataset(client: AsyncClient, name: str, rows: list[str]) -> dict:
    upload = await client.post(
        "/api/datasets/upload",
        files={"file": (f"{name}.csv", "\n".join(rows).encode(), "text/csv")},
    )
    assert upload.status_code == 201, upload.text
    return dict(upload.json()["dataset"])


def _monthly(columns: str, row: str, months: int = 36) -> list[str]:
    return [columns] + [
        f"{date(2021, 1, 1) + relativedelta(months=index):%Y-%m-%d},{row.format(i=index)}"
        for index in range(months)
    ]


async def test_a_text_column_cannot_be_the_target(client: AsyncClient) -> None:
    dataset = await _dataset(client, "typed", _monthly("month,revenue,note", "{i}00,note-{i}"))

    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": dataset["id"], "target_column": "note", "horizon": 6},
    )

    assert response.status_code == 422, response.text
    body = response.json()["error"]
    assert "note" in body["message"]
    assert body["detail"]["required_kind"] == "numeric"
    assert "revenue" in body["detail"]["candidates"]


async def test_a_numeric_column_cannot_be_the_time_column(client: AsyncClient) -> None:
    dataset = await _dataset(client, "timed", _monthly("month,revenue", "{i}00"))

    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": dataset["id"], "time_column": "revenue", "horizon": 6},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["detail"]["required_kind"] == "date"


async def test_a_driver_that_cannot_be_read_is_refused_rather_than_dropped(
    client: AsyncClient,
) -> None:
    dataset = await _dataset(client, "drivers", _monthly("month,revenue,region", "{i}00,north"))

    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": dataset["id"], "driver_columns": ["region"], "horizon": 6},
    )

    assert response.status_code == 422, response.text
    assert "region" in response.json()["error"]["message"]


async def test_a_driver_that_is_not_in_the_dataset_is_refused(client: AsyncClient) -> None:
    dataset = await _dataset(client, "nodriver", _monthly("month,revenue", "{i}00"))

    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": dataset["id"], "driver_columns": ["web_sessions"], "horizon": 6},
    )

    assert response.status_code == 422, response.text
    assert "web_sessions" in response.json()["error"]["message"]


async def test_a_model_name_the_engine_does_not_know_is_refused(client: AsyncClient) -> None:
    dataset = await _dataset(client, "roster", _monthly("month,revenue", "{i}00"))

    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": dataset["id"], "candidate_models": ["lstm"], "horizon": 6},
    )

    assert response.status_code == 422, response.text


async def test_a_roster_that_fits_nothing_fails_the_run_rather_than_running_everything(
    client: AsyncClient,
) -> None:
    """Croston is only offered for intermittent demand. Asked for on a smooth
    series the filter came back empty, and an empty filter fell back to the
    whole roster — so a run restricted to one model ran nine, and reported the
    winner as though it had been the one asked for."""
    dataset = await _dataset(client, "wrongmodel", _monthly("month,revenue", "{i}00"))

    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": dataset["id"], "candidate_models": ["croston"], "horizon": 6},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]

    async with client.stream("GET", f"/api/forecasts/{run_id}/events") as stream:
        async for _ in stream.aiter_lines():
            pass

    detail = (await client.get(f"/api/forecasts/{run_id}")).json()

    assert detail["status"] == "failed"
    assert "croston" in (detail["error_message"] or "").lower()


async def test_a_horizon_longer_than_the_history_is_refused(client: AsyncClient) -> None:
    dataset = await _dataset(client, "shorthist", _monthly("month,revenue", "{i}00", months=12))

    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": dataset["id"], "horizon": 24},
    )

    assert response.status_code == 422, response.text
    detail = response.json()["error"]["detail"]
    assert detail["periods_available"] == 12
    assert detail["max_horizon"] == 6


async def test_a_horizon_the_history_supports_is_accepted(client: AsyncClient) -> None:
    dataset = await _dataset(client, "longhist", _monthly("month,revenue", "{i}00", months=36))

    response = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": dataset["id"], "horizon": 12},
    )

    assert response.status_code == 202, response.text


async def test_the_default_horizon_is_shortened_rather_than_refused(client: AsyncClient) -> None:
    """Refusing a run over a number nobody typed is no more helpful than
    answering a question nobody asked. A horizon somebody chose is refused; the
    default is held to what the history supports."""
    dataset = await _dataset(client, "tiny", _monthly("month,revenue", "{i}00", months=6))

    response = await client.post("/api/forecasts/run", json={"dataset_id": dataset["id"]})

    assert response.status_code == 202, response.text
    assert response.json()["horizon"] == 3
