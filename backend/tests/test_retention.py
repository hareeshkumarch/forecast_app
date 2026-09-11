from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.config import settings
from app.database.base import utcnow
from app.models.entities import Dataset, ForecastRun, ForecastScenario
from app.models.enums import DatasetStatus, ForecastFrequency, RunStatus
from app.services import capacity_service, retention_service


@pytest.fixture(autouse=True)
def _policy():
    before = (
        settings.retention_enabled,
        settings.retention_run_days,
        settings.retention_keep_runs,
        settings.retention_batch,
    )
    settings.retention_enabled = True
    settings.retention_run_days = 30
    settings.retention_keep_runs = 2
    settings.retention_batch = 10
    capacity_service.forget()
    yield
    (
        settings.retention_enabled,
        settings.retention_run_days,
        settings.retention_keep_runs,
        settings.retention_batch,
    ) = before
    capacity_service.forget()


async def _dataset(session) -> Dataset:
    dataset = Dataset(name="retention fixture", status=DatasetStatus.READY)
    session.add(dataset)
    await session.flush()
    return dataset


async def _run(session, *, days_old: int, status: RunStatus = RunStatus.COMPLETED) -> ForecastRun:
    when = utcnow() - timedelta(days=days_old)
    run = ForecastRun(
        id=uuid.uuid4(),
        dataset_id=(await _dataset(session)).id,
        name=f"run {days_old} days old",
        time_column="week",
        target_column="units",
        frequency=ForecastFrequency.WEEKLY,
        horizon=4,
        status=status,
        stage="complete" if status is RunStatus.COMPLETED else "queued",
        progress=1.0 if status is RunStatus.COMPLETED else 0.0,
        created_at=when,
        updated_at=when,
        completed_at=when if status in (RunStatus.COMPLETED, RunStatus.FAILED) else None,
    )
    session.add(run)
    await session.flush()
    return run


async def test_an_old_finished_run_is_a_candidate(session) -> None:
    for age in (400, 300, 200, 100):
        await _run(session, days_old=age)
    await session.commit()

    intended = await retention_service.plan(session)

    assert intended.would_remove == 2
    assert intended.enabled


async def test_a_recent_run_is_not(session) -> None:
    for age in (1, 2, 3, 4):
        await _run(session, days_old=age)
    await session.commit()

    assert (await retention_service.plan(session)).would_remove == 0


async def test_the_newest_runs_are_kept_however_old_they_are() -> None:
    from app.database.session import session_scope

    async with session_scope() as session:
        for age in (500, 600, 700):
            await _run(session, days_old=age)

    async with session_scope() as session:
        intended = await retention_service.plan(session)

    assert intended.would_remove == 1
    assert len(intended.protected) == 2
    assert any("most recent" in reason for reason in intended.protected.values())
    assert any("dashboard" in reason for reason in intended.protected.values())


async def test_a_run_that_has_not_finished_is_never_a_candidate(session) -> None:
    for age in (400, 401, 402):
        await _run(session, days_old=age)
    live = await _run(session, days_old=500, status=RunStatus.RUNNING)
    await session.commit()

    intended = await retention_service.plan(session)

    assert live.id not in {row.run_id for row in intended.removing}


async def test_the_run_the_dashboard_is_showing_is_never_a_candidate(session) -> None:
    newest = await _run(session, days_old=100)
    for age in (400, 401, 402):
        await _run(session, days_old=age)
    await session.commit()

    intended = await retention_service.plan(session)

    assert newest.id not in {row.run_id for row in intended.removing}
    assert "dashboard" in " ".join(intended.protected.values())


async def test_a_run_a_saved_scenario_points_at_is_never_a_candidate(session) -> None:
    for age in (100, 200):
        await _run(session, days_old=age)
    referenced = await _run(session, days_old=900)
    for age in (901, 902):
        await _run(session, days_old=age)

    session.add(
        ForecastScenario(
            id=uuid.uuid4(),
            run_id=referenced.id,
            name="Peak season",
            volume_multiplier=1.1,
        )
    )
    await session.commit()

    intended = await retention_service.plan(session)

    assert referenced.id not in {row.run_id for row in intended.removing}
    assert "saved scenario" in " ".join(intended.protected.values())


async def test_a_backlog_is_reported_as_a_backlog(session) -> None:
    settings.retention_batch = 2
    for age in range(100, 112):
        await _run(session, days_old=age * 10)
    await session.commit()

    intended = await retention_service.plan(session)

    assert intended.would_remove == 2
    assert intended.remaining == 8


async def test_switched_off_the_preview_still_answers(session) -> None:
    settings.retention_enabled = False
    for age in (400, 401, 402, 403):
        await _run(session, days_old=age)
    await session.commit()

    intended = await retention_service.plan(session)

    assert not intended.enabled
    assert intended.would_remove == 2


async def test_switched_off_a_sweep_removes_nothing() -> None:
    from app.database.session import session_scope

    settings.retention_enabled = False
    async with session_scope() as session:
        for age in (400, 401, 402, 403):
            await _run(session, days_old=age)

    result = await retention_service.sweep()

    assert result.would_remove == 0
    async with session_scope() as session:
        assert await retention_service.stored_runs(session) == 4


async def test_a_pass_asked_for_by_hand_runs_on_a_deployment_with_it_off() -> None:
    from app.database.session import session_scope

    settings.retention_enabled = False
    async with session_scope() as session:
        for age in (400, 401, 402, 403):
            await _run(session, days_old=age)

    result = await retention_service.sweep(force=True)

    assert result.would_remove == 2
    async with session_scope() as session:
        assert await retention_service.stored_runs(session) == 2


async def test_zero_days_means_age_is_not_a_reason_on_its_own(session) -> None:
    settings.retention_run_days = 0
    for age in (1, 2, 3, 4):
        await _run(session, days_old=age)
    await session.commit()

    assert (await retention_service.plan(session)).would_remove == 2


class TestCapacity:
    async def test_it_reports_the_tables_that_exist(self, session) -> None:
        usage = await capacity_service.measure(session, fresh=True)

        assert usage.tables
        assert {"forecast_runs", "datasets"} <= {table.name for table in usage.tables}

    async def test_rows_are_counted(self, session) -> None:
        for age in (1, 2, 3):
            await _run(session, days_old=age)
        await session.commit()

        usage = await capacity_service.measure(session, fresh=True)
        runs = next(table for table in usage.tables if table.name == "forecast_runs")

        assert runs.rows == 3

    async def test_a_repeat_read_is_served_from_the_cache(self, session) -> None:
        first = await capacity_service.measure(session, fresh=True)
        second = await capacity_service.measure(session)

        assert second is first

    async def test_asking_for_it_fresh_bypasses_the_cache(self, session) -> None:
        first = await capacity_service.measure(session, fresh=True)
        second = await capacity_service.measure(session, fresh=True)

        assert second is not first


class TestTheEndpoints:
    async def test_the_preview_removes_nothing(self, client, session) -> None:
        for age in (400, 401, 402, 403):
            await _run(session, days_old=age)
        await session.commit()

        response = await client.get("/api/forecasts/retention")

        assert response.status_code == 200
        assert len(response.json()["runs"]) == 2
        assert await retention_service.stored_runs(session) == 4

    async def test_a_pass_removes_what_the_preview_named(self, client) -> None:
        from app.database.session import session_scope

        async with session_scope() as session:
            for age in (400, 401, 402, 403):
                await _run(session, days_old=age)

        response = await client.post("/api/forecasts/retention")

        assert response.status_code == 200
        assert len(response.json()["runs"]) == 2
        async with session_scope() as session:
            assert await retention_service.stored_runs(session) == 2

    async def test_the_reasons_travel_with_the_answer(self, client, session) -> None:
        for age in (400, 401, 402):
            await _run(session, days_old=age)
        await session.commit()

        body = (await client.get("/api/forecasts/retention")).json()

        assert body["protected"]
        assert all(isinstance(reason, str) and reason for reason in body["protected"].values())

    async def test_it_is_gated_as_a_deletion_rather_than_as_a_run(self) -> None:
        from app.core.permissions import Permission, permission_for

        assert permission_for("POST", "/api/forecasts/retention") is Permission.FORECAST_DELETE
        assert permission_for("GET", "/api/forecasts/retention") is Permission.READ

    def test_it_does_not_spend_the_hourly_forecast_allowance(self) -> None:
        from app.core import ratelimit

        assert ratelimit.rule_for("POST", "/api/forecasts/retention") is ratelimit.ADMIN


class TestStorageEndpoint:
    async def test_it_reports_what_is_stored(self, client, session) -> None:
        await _run(session, days_old=1)
        await session.commit()

        body = (await client.get("/api/health/storage")).json()

        assert body["total_rows"] > 0
        assert body["stored_runs"] == 1
        assert any(table["name"] == "forecast_runs" for table in body["tables"])

    async def test_it_says_what_retention_would_do(self, client, session) -> None:
        for age in (400, 401, 402, 403):
            await _run(session, days_old=age)
        await session.commit()

        body = (await client.get("/api/health/storage")).json()

        assert body["prunable_runs"] == 2
        assert body["retention_keep_runs"] == settings.retention_keep_runs

    async def test_it_needs_the_metrics_token_where_one_is_set(self, client) -> None:
        before = settings.metrics_token
        settings.metrics_token = "a-real-token"
        try:
            assert (await client.get("/api/health/storage")).status_code == 401
            allowed = await client.get(
                "/api/health/storage", headers={"Authorization": "Bearer a-real-token"}
            )
            assert allowed.status_code == 200
        finally:
            settings.metrics_token = before
