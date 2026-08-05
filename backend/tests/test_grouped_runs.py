"""
A run that forecasts a grain rather than one total.

The fan-out itself is proved against a real broker in `test_worker_roundtrip`;
what is checked here is everything that has to hold whether the leaves were
fitted here or on twenty other machines — the wire format, the tree, and the
fact that a series that failed to fit cannot take its parents with it.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.database.sample_data import generate_csv_bytes
from app.forecasting.engine import LeafFit, SegmentInput, assemble_grouped
from app.forecasting.frequency import add_periods
from app.models.entities import ForecastSeries
from app.models.enums import ForecastFrequency, PointKind, RunStatus, SeriesStatus
from app.services import dataset_service, forecast_service, series_service
from app.services.job_runner import ProgressEvent, progress_bus

MONTHLY = ForecastFrequency.MONTHLY
GRAIN = ["region", "product_category"]
REGION_ONLY = ["region"]


async def _dataset(session: AsyncSession) -> uuid.UUID:
    dataset, _profile = await dataset_service.create_from_upload(
        session, generate_csv_bytes(), "panel.csv", name="Panel"
    )
    await session.commit()
    return dataset.id


async def _run_grouped(session: AsyncSession, grain: list[str] | None) -> uuid.UUID:
    dataset_id = await _dataset(session)
    run = await forecast_service.create_run(
        session,
        dataset_id=dataset_id,
        name="grouped",
        horizon=3,
        max_folds=1,
        group_by=grain,
    )
    run_id = run.id
    await session.commit()

    status = await forecast_service.execute_run(run_id)
    assert status is RunStatus.COMPLETED, "a single-node grouped run finishes in place"
    session.expire_all()
    return run_id


async def _series(session: AsyncSession, run_id: uuid.UUID) -> list[ForecastSeries]:
    result = await session.execute(
        select(ForecastSeries).where(ForecastSeries.run_id == run_id).order_by(ForecastSeries.level)
    )
    return list(result.scalars().all())


# ------------------------------------------------------- the tree, end to end


async def test_a_grouped_run_forecasts_every_series_in_the_grain(session: AsyncSession) -> None:
    run_id = await _run_grouped(session, GRAIN)
    rows = await _series(session, run_id)

    assert {row.level for row in rows} == {0, 1, 2}

    leaves = [row for row in rows if row.level == 2]
    assert len(leaves) == 25, "five regions times five categories"
    assert all(row.parent_id is not None for row in rows if row.level > 0)
    assert all(row.parent_id is None for row in rows if row.level == 0)

    root = next(row for row in rows if row.level == 0)
    for level in (1, 2):
        assert sum(row.forecast_total for row in rows if row.level == level) == pytest.approx(
            root.forecast_total, rel=1e-6
        ), f"level {level} does not close on the total"

    stored = await forecast_service.get_run(session, run_id)
    assert stored.series_count == len(rows)
    assert stored.group_by == GRAIN


async def test_a_series_curve_is_kept_apart_from_the_headline(session: AsyncSession) -> None:
    run_id = await _run_grouped(session, REGION_ONLY)

    headline = await forecast_service.points_for_run(session, run_id)
    assert headline, "the run keeps its own top line"
    assert all(point.series_id is None for point in headline)

    leaf = next(row for row in await _series(session, run_id) if row.level == 1)
    scoped = await forecast_service.points_for_run(session, run_id, series_id=leaf.id)

    assert scoped, "a series stores a curve of its own"
    assert all(point.series_id == leaf.id for point in scoped)
    assert sum(point.forecast or 0.0 for point in scoped) == pytest.approx(
        leaf.forecast_total, rel=1e-6
    )


async def test_the_headline_is_the_top_line_not_the_sum_of_the_tree(session: AsyncSession) -> None:
    from app.schemas.dashboard import DashboardQuery
    from app.services import dashboard_service

    run_id = await _run_grouped(session, REGION_ONLY)

    summary = await dashboard_service.summary(session, DashboardQuery(run_id=run_id))
    card = next(kpi for kpi in summary.kpis if kpi.key == "total_forecast")

    points = await forecast_service.points_for_run(session, run_id)
    direct = sum(p.forecast or 0.0 for p in points if p.kind is PointKind.FORECAST)

    # Every series stores its own forecast points too; the KPI must count the
    # run's own line once rather than summing the whole tree on top of it.
    assert card.value == pytest.approx(direct, rel=1e-6)


async def test_a_run_without_a_grain_stores_no_series(session: AsyncSession) -> None:
    run_id = await _run_grouped(session, None)

    assert await _series(session, run_id) == []

    stored = await forecast_service.get_run(session, run_id)
    assert stored.group_by == []
    assert stored.series_count == 0


async def test_a_grouped_run_reports_progress_that_only_moves_forward(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames: list[ProgressEvent] = []
    announce = progress_bus.publish

    def spy(event: ProgressEvent) -> None:
        frames.append(event)
        announce(event)

    monkeypatch.setattr(progress_bus, "publish", spy)

    run_id = await _run_grouped(session, REGION_ONLY)
    mine = [frame for frame in frames if frame.run_id == run_id]
    stages = [frame.stage for frame in mine]

    assert "fitting_series" in stages, "the fan-out has to be visible while it runs"
    assert stages[-1] == "complete"

    # The series work lands after the top line, so the bar must never rewind.
    progress = [frame.progress for frame in mine]
    assert progress == sorted(progress), stages


# ------------------------------------------------------------ the grain itself


@pytest.mark.parametrize(
    "grain",
    [
        pytest.param(["not_a_column"], id="unknown column"),
        pytest.param(["region", "region"], id="the same column twice"),
        pytest.param(["order_date"], id="the time column"),
        pytest.param(["revenue"], id="the target column"),
    ],
)
async def test_a_grain_is_checked_before_the_run_is_queued(
    session: AsyncSession, grain: list[str]
) -> None:
    dataset_id = await _dataset(session)

    with pytest.raises(ValidationError):
        await forecast_service.create_run(session, dataset_id=dataset_id, group_by=grain)


# ------------------------------------------------------------- the wire format


def _leaf(label: str, base: float, slope: float) -> SegmentInput:
    periods = [add_periods(date(2021, 1, 1), i, MONTHLY) for i in range(36)]
    t = np.arange(36)
    values = base + slope * t + 40 * np.sin(2 * np.pi * t / 12)
    return SegmentInput(
        label=label,
        current_total=float(np.sum(values[-12:])),
        prior_total=float(np.sum(values[-24:-12])),
        series=[float(v) for v in values[-12:]],
        periods=periods,
        values=[float(v) for v in values],
        key={"region": label.split(" · ")[0], "sku": label.split(" · ")[-1]},
    )


def test_a_chunk_survives_the_trip_a_broker_would_put_it_through() -> None:
    leaves = [_leaf("North · A", 900.0, 12.0), _leaf("South · B", 400.0, -6.0)]
    plan = series_service.GroupedPlan(
        leaves=leaves,
        group_by=["region", "sku"],
        frequency=MONTHLY,
        horizon=3,
        max_folds=1,
        confidence_level=0.8,
        total_path=[1000.0, 1000.0, 1000.0],
        forecast_periods=[date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
    )

    # Dates and numpy scalars do not survive JSON, and a broker carries nothing
    # else — so the round trip is the test.
    job = json.loads(json.dumps(series_service._chunk_job(uuid.uuid4(), plan, leaves)))
    returned = json.loads(json.dumps(series_service.run_chunk_job(job)))

    fits = [LeafFit.from_dict(row) for row in returned]
    assert [fit.label for fit in fits] == ["North · A", "South · B"]
    assert all(fit.fitted for fit in fits)
    assert all(len(fit.forecast or []) == 3 for fit in fits)
    assert all(fit.model is not None for fit in fits)


def test_a_chunk_that_could_not_be_fitted_still_answers_for_its_series() -> None:
    job = {"leaves": [{"label": "North · A"}, {"label": "South · B"}]}

    fits = [LeafFit.from_dict(row) for row in series_service.blocked_chunk(job, "worker lost")]

    assert [fit.label for fit in fits] == ["North · A", "South · B"]
    assert all(not fit.fitted for fit in fits)
    assert all(fit.blocked_reason == "worker lost" for fit in fits)


def test_a_series_that_never_came_back_is_apportioned_rather_than_dropped() -> None:
    leaves = [_leaf("North · A", 900.0, 12.0), _leaf("South · B", 400.0, -6.0)]
    total = np.array([1000.0, 1000.0, 1000.0])

    results = assemble_grouped(
        leaves,
        [
            LeafFit(label="North · A", forecast=[600.0, 700.0, 800.0], model=None, wmape=0.1),
            LeafFit(label="South · B", blocked_reason="worker lost"),
        ],
        ["region", "sku"],
        total,
    )

    lost = next(row for row in results if row.label == "South · B")
    assert lost.status is SeriesStatus.ESTIMATED
    assert lost.blocked_reason == "worker lost"
    assert lost.accuracy_measured is False
    assert lost.forecast_total > 0, "a lost series still gets a number from its parent"

    root = next(row for row in results if row.level == 0)
    assert sum(row.forecast_total for row in results if row.level == 2) == pytest.approx(
        root.forecast_total, rel=1e-6
    )
    assert root.forecast_total == pytest.approx(float(np.sum(total)), rel=1e-6)


def test_a_fit_survives_being_written_down_and_read_back() -> None:
    fit = LeafFit(
        label="North · A",
        forecast=[1.0, 2.0, 3.0],
        model=None,
        wmape=12.34,
        folds=3,
    )

    restored = LeafFit.from_dict(json.loads(json.dumps(fit.to_dict())))

    assert restored == fit
    assert restored.accuracy == pytest.approx(87.66), "wmape is carried as a percentage"
    assert LeafFit(label="x").accuracy is None
