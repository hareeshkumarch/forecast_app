
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.database.sample_data import generate_csv_bytes
from app.database.seed import seed_connectors


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
    assert len(types) == 10
    bigquery = next(item for item in types if item["type"] == "bigquery")
    assert any(field["secret"] for field in bigquery["fields"])


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

    assert run["selected_model"] in {
        "naive",
        "seasonal_naive",
        "holt_winters",
        "sarimax",
        "gradient_boosting",
    }
    assert run["selection_rationale"]
    assert run["progress"] == 1.0
    assert run["forecast_start"] and run["forecast_end"]


async def test_metrics_expose_every_candidate_and_the_scoring_rule(client: AsyncClient) -> None:
    run = await _seed_and_run(client)

    response = await client.get(f"/api/forecasts/{run['id']}/metrics")
    assert response.status_code == 200

    body = response.json()
    assert "norm(wMAPE)" in body["scoring_rule"]
    assert len(body["candidates"]) == 5
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


async def test_regions_categories_and_drivers(client: AsyncClient) -> None:
    await _seed_and_run(client)

    regions = (await client.get("/api/dashboard/regions")).json()
    categories = (await client.get("/api/dashboard/categories")).json()
    drivers = (await client.get("/api/dashboard/drivers")).json()

    assert len(regions["rows"]) == 5
    assert len(categories["rows"]) == 5
    assert len(drivers["rows"]) == 5

                                                         
    assert sum(r["forecast_value"] for r in regions["rows"]) == pytest.approx(
        regions["total"], rel=1e-6
    )
    assert sum(c["share"] for c in categories["rows"]) == pytest.approx(100.0, abs=0.1)


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


@pytest.mark.parametrize("fmt", ["csv", "json", "xlsx"])
async def test_export_formats(client: AsyncClient, fmt: str) -> None:
    run = await _seed_and_run(client)

    response = await client.get(f"/api/exports/{run['id']}?format={fmt}")
    assert response.status_code == 200
    assert len(response.content) > 0
    assert "attachment" in response.headers["content-disposition"]


async def test_export_of_missing_run_is_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/exports/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.parametrize("prefix", ["datasets", "forecasts", "connectors"])
async def test_unknown_ids_return_404(client: AsyncClient, prefix: str) -> None:
    response = await client.get(f"/api/{prefix}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
