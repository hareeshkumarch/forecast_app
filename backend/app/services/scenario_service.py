from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.forecasting.metrics import accuracy_from_wmape
from app.models.entities import ForecastPoint, ForecastRun, ForecastScenario
from app.models.enums import PointKind, RunStatus
from app.schemas.forecast import (
    ForecastMonitoringResponse,
    ForecastMonitorItem,
    RunComparisonResponse,
    RunComparisonSnapshot,
    RunMetricComparison,
    SavedScenarioCreate,
    WhatIfSimulationResponse,
)
from app.services import forecast_service


async def list_scenarios(
    session: AsyncSession, run_id: uuid.UUID
) -> list[ForecastScenario]:
    await forecast_service.get_run_state(session, run_id)
    result = await session.execute(
        select(ForecastScenario)
        .where(ForecastScenario.run_id == run_id)
        .order_by(ForecastScenario.created_at.desc(), ForecastScenario.id.desc())
    )
    return list(result.scalars().all())


async def save_scenario(
    session: AsyncSession,
    run_id: uuid.UUID,
    payload: SavedScenarioCreate,
) -> ForecastScenario:
    simulation = await forecast_service.simulate_what_if(
        session,
        run_id,
        volume_multiplier=payload.volume_multiplier,
        target_shift_pct=payload.target_shift_pct,
        driver_multipliers=payload.driver_multipliers,
    )
    scenario = ForecastScenario(
        run_id=run_id,
        name=payload.name,
        description=payload.description,
        volume_multiplier=payload.volume_multiplier,
        target_shift_pct=payload.target_shift_pct,
        driver_multipliers=dict(payload.driver_multipliers),
        result=WhatIfSimulationResponse.model_validate(simulation).model_dump(mode="json"),
    )
    session.add(scenario)
    await session.flush()
    return scenario


async def delete_scenario(
    session: AsyncSession, run_id: uuid.UUID, scenario_id: uuid.UUID
) -> None:
    result = await session.execute(
        delete(ForecastScenario).where(
            ForecastScenario.id == scenario_id,
            ForecastScenario.run_id == run_id,
        )
    )
    if not result.rowcount:
        raise NotFoundError(f"No saved scenario with id {scenario_id} exists for this run.")


async def _forecast_total(session: AsyncSession, run_id: uuid.UUID) -> float:
    result = await session.execute(
        select(func.coalesce(func.sum(ForecastPoint.forecast), 0.0)).where(
            ForecastPoint.run_id == run_id,
            ForecastPoint.kind == PointKind.FORECAST,
            ForecastPoint.series_id.is_(None),
        )
    )
    return round(float(result.scalar_one()), 4)


def _accuracy(wmape: float | None) -> float | None:
    if wmape is None:
        return None
    value = accuracy_from_wmape(wmape)
    return None if value != value else round(float(value), 2)


async def _snapshot(session: AsyncSession, run: ForecastRun) -> RunComparisonSnapshot:
    return RunComparisonSnapshot(
        run_id=run.id,
        name=run.name,
        dataset_id=run.dataset_id,
        model=run.selected_model,
        frequency=run.frequency,
        horizon=run.horizon,
        confidence_level=run.confidence_level,
        forecast_total=await _forecast_total(session, run.id),
        realized_accuracy=_accuracy(run.realized_wmape),
        realized_wmape=run.realized_wmape,
        realized_bias=run.realized_bias,
        realized_coverage=run.realized_coverage,
        created_at=run.created_at,
    )


async def compare_runs(
    session: AsyncSession, left_run_id: uuid.UUID, right_run_id: uuid.UUID
) -> RunComparisonResponse:
    if left_run_id == right_run_id:
        raise ValidationError("Choose two different forecast runs to compare.")

    left = await forecast_service.get_run(session, left_run_id)
    right = await forecast_service.get_run(session, right_run_id)
    left_snapshot = await _snapshot(session, left)
    right_snapshot = await _snapshot(session, right)

    left_metrics = {metric.name: metric for metric in left.metrics}
    right_metrics = {metric.name: metric for metric in right.metrics}
    metrics: list[RunMetricComparison] = []
    for name in sorted(set(left_metrics) | set(right_metrics)):
        left_metric = left_metrics.get(name)
        right_metric = right_metrics.get(name)
        left_value = float(left_metric.value) if left_metric else None
        right_value = float(right_metric.value) if right_metric else None
        delta = None if left_value is None or right_value is None else right_value - left_value
        delta_pct = (
            None
            if delta is None or left_value == 0
            else round(delta / abs(left_value) * 100.0, 2)
        )
        metrics.append(
            RunMetricComparison(
                name=name,
                unit=(right_metric or left_metric).unit,  # type: ignore[union-attr]
                left=left_value,
                right=right_value,
                delta=None if delta is None else round(delta, 4),
                delta_pct=delta_pct,
            )
        )

    total_delta = right_snapshot.forecast_total - left_snapshot.forecast_total
    total_delta_pct = (
        None
        if left_snapshot.forecast_total == 0
        else round(total_delta / abs(left_snapshot.forecast_total) * 100.0, 2)
    )
    return RunComparisonResponse(
        left=left_snapshot,
        right=right_snapshot,
        forecast_total_delta=round(total_delta, 4),
        forecast_total_delta_pct=total_delta_pct,
        metrics=metrics,
    )


def _monitor_item(run: ForecastRun) -> ForecastMonitorItem:
    alert: str | None = None
    level: str | None = None
    drifted = bool(
        run.realized_wmape is not None
        and run.realized_wmape > settings.drift_wmape_limit
    )

    if run.status == RunStatus.FAILED:
        alert = run.error_message or "The run failed before producing a forecast."
        level = "critical"
    elif run.status in (RunStatus.PENDING, RunStatus.RUNNING):
        alert = f"Run is {run.stage.replace('_', ' ')}."
        level = "info"
    elif drifted:
        alert = (
            f"Realized wMAPE is {run.realized_wmape:.1f}%, above the "
            f"{settings.drift_wmape_limit:.1f}% drift limit."
        )
        level = "warning"
    elif (
        run.realized_wmape is not None
        and _accuracy(run.realized_wmape) is not None
        and _accuracy(run.realized_wmape) < settings.insight_accuracy_warning
    ):
        alert = "Realized accuracy is below the review threshold."
        level = "warning"
    elif run.forecast_end is not None and run.forecast_end <= date.today() and not run.scored_periods:
        alert = "Forecast periods have elapsed; score this run against the latest actuals."
        level = "warning"

    return ForecastMonitorItem(
        run_id=run.id,
        name=run.name,
        status=run.status,
        model=run.selected_model,
        completed_at=run.completed_at,
        forecast_end=run.forecast_end,
        scored_at=run.scored_at,
        scored_periods=run.scored_periods,
        realized_accuracy=_accuracy(run.realized_wmape),
        realized_wmape=run.realized_wmape,
        realized_bias=run.realized_bias,
        realized_coverage=run.realized_coverage,
        alert=alert,
        alert_level=level,
        drifted=drifted,
        can_retry=run.status == RunStatus.FAILED,
    )


async def monitoring(session: AsyncSession, *, limit: int = 50) -> ForecastMonitoringResponse:
    result = await session.execute(
        select(ForecastRun)
        .order_by(ForecastRun.created_at.desc(), ForecastRun.id.desc())
        .limit(limit)
    )
    rows = [_monitor_item(run) for run in result.scalars().all()]
    attention = sum(1 for row in rows if row.alert_level == "warning")
    failed = sum(1 for row in rows if row.status == RunStatus.FAILED)
    active = sum(1 for row in rows if row.status in (RunStatus.PENDING, RunStatus.RUNNING))
    healthy = sum(1 for row in rows if row.alert is None)
    return ForecastMonitoringResponse(
        total=len(rows),
        healthy=healthy,
        attention=attention,
        failed=failed,
        active=active,
        drift_wmape_limit=settings.drift_wmape_limit,
        rows=rows,
    )
