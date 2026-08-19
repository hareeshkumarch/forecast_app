from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.numbers import finite
from app.database.session import session_scope
from app.datasets import queries
from app.datasets.queries import DEFAULT_MAX_SERIES
from app.forecasting.engine import (
    LeafFit,
    SegmentInput,
    SeriesResult,
    assemble_grouped,
    fit_leaf,
)
from app.forecasting.frequency import comparison_window
from app.forecasting.preparation import Preparation
from app.models.entities import ForecastPoint, ForecastRun, ForecastSeries
from app.models.enums import (
    ForecastFrequency,
    GapFill,
    MeasureAggregation,
    OutlierTreatment,
    PointKind,
    RunStatus,
    SeriesStatus,
)
from app.services.job_runner import ProgressEvent, executors, publish_progress
from app.services.progress_relay import count_series, forget_series_count

logger = get_logger(__name__)

FAN_OUT_CHUNK = settings.series_fan_out_chunk

FIT_FROM, FIT_TO = 0.68, 0.94
STORE_AT = 0.96


@dataclass(slots=True)
class GroupedPlan:
    leaves: list[SegmentInput]
    group_by: list[str]
    frequency: ForecastFrequency
    horizon: int
    max_folds: int | None
    confidence_level: float
    total_path: list[float]
    forecast_periods: list[date]
    #: The run's gap-fill setting, carried down so a series under the total is
    #: prepared by the same rules as the total. Sent as the two plain values
    #: rather than as a `Preparation`, because this plan crosses a Celery
    #: boundary and only what JSON can carry survives it.
    gap_fill: GapFill = GapFill.NONE
    winsorise_sigmas: float | None = None


async def plan_for(run_id: uuid.UUID) -> GroupedPlan | None:
    from app.services import dataset_service, forecast_service

    async with session_scope() as session:
        run = await forecast_service.get_run_state(session, run_id)
        if run.status is not RunStatus.RUNNING:
            return None
        group_by = [str(column) for column in (run.group_by or [])]
        if not group_by:
            return None

        dataset = await dataset_service.get_dataset(session, run.dataset_id)
        parquet_path = Path(dataset.parquet_path or "")
        overrides = forecast_service.RunOverrides.from_stored(run.options)

        periods, total_path = await _stored_total(session, run_id)
        frequency, horizon = run.frequency, run.horizon
        confidence_level = run.confidence_level
        time_column, target_column = run.time_column, run.target_column
        aggregation = run.aggregation
        gap_fill = run.gap_fill
        winsorise_sigmas = (
            (overrides.outlier_mad_threshold or forecast_service.WINSORISE_SIGMAS)
            if run.outlier_treatment is OutlierTreatment.WINSORISE
            else None
        )
        max_series = max(1, min(overrides.max_series or DEFAULT_MAX_SERIES, DEFAULT_MAX_SERIES))

    leaves = await asyncio.to_thread(
        _aggregate_leaves,
        parquet_path,
        time_column,
        target_column,
        group_by,
        frequency,
        aggregation,
        max_series,
    )

    return GroupedPlan(
        leaves=leaves,
        group_by=group_by,
        frequency=frequency,
        horizon=horizon,
        max_folds=overrides.max_folds,
        confidence_level=confidence_level,
        total_path=total_path,
        forecast_periods=periods,
        gap_fill=gap_fill,
        winsorise_sigmas=winsorise_sigmas,
    )


def _aggregate_leaves(
    parquet_path: Path,
    time_column: str,
    target_column: str,
    group_by: list[str],
    frequency: ForecastFrequency,
    aggregation: MeasureAggregation,
    max_series: int,
) -> list[SegmentInput]:
    grouped = queries.aggregate_grouped(
        parquet_path,
        time_column,
        target_column,
        group_by,
        frequency,
        aggregation=aggregation,
        max_series=max_series,
    )
    window = comparison_window(frequency, len(grouped[0].periods)) if grouped else 1

    return [
        SegmentInput(
            label=series.label,
            current_total=series.current_total,
            prior_total=series.prior_total,
            series=series.values[-window:],
            periods=series.periods,
            values=series.values,
            key=series.key,
        )
        for series in grouped
    ]


async def _stored_total(session: AsyncSession, run_id: uuid.UUID) -> tuple[list[date], list[float]]:
    result = await session.execute(
        select(ForecastPoint.period, ForecastPoint.forecast)
        .where(
            ForecastPoint.run_id == run_id,
            ForecastPoint.series_id.is_(None),
            ForecastPoint.kind == PointKind.FORECAST,
        )
        .order_by(ForecastPoint.period)
    )
    rows = result.all()
    return [row[0] for row in rows], [float(row[1] or 0.0) for row in rows]


async def forecast_series(run_id: uuid.UUID) -> RunStatus:
    from app.services import forecast_service

    plan = await plan_for(run_id)
    if plan is None:
        return RunStatus.FAILED
    if not plan.leaves:
        logger.info("Run %s has a grain but no series to forecast.", run_id)
        completed = await forecast_service.complete_run(run_id)
        return RunStatus.COMPLETED if completed else RunStatus.FAILED

    if not await forecast_service.checkpoint_progress(
        run_id,
        FIT_FROM,
        "fitting_series",
        f"Forecasting series 0 of {len(plan.leaves):,}...",
    ):
        return RunStatus.FAILED

    if settings.distributed:
        forget_series_count(run_id)
        dispatch(run_id, plan)
        return RunStatus.RUNNING

    fits = await _fit_here(run_id, plan)
    return await finalise(run_id, fits, plan=plan)


async def _fit_here(run_id: uuid.UUID, plan: GroupedPlan) -> list[LeafFit]:
    chunks = _chunks(plan.leaves)
    done = 0
    fits: list[LeafFit] = []

    pending = [
        executors.run(
            fit_chunk,
            [_payload(leaf) for leaf in chunk],
            plan.frequency,
            plan.horizon,
            plan.max_folds,
            plan.confidence_level,
            plan.gap_fill,
            plan.winsorise_sigmas,
        )
        for chunk in chunks
    ]

    for coroutine in asyncio.as_completed(pending):
        chunk_fits = [LeafFit.from_dict(row) for row in await coroutine]
        fits.extend(chunk_fits)
        done += len(chunk_fits)
        _publish_fitting(run_id, done, len(plan.leaves))

    return fits


def fit_chunk(
    payloads: list[dict[str, Any]],
    frequency: ForecastFrequency,
    horizon: int,
    max_folds: int | None,
    confidence_level: float,
    gap_fill: GapFill = GapFill.NONE,
    winsorise_sigmas: float | None = None,
) -> list[dict[str, Any]]:
    preparation = Preparation(fill=GapFill(gap_fill), winsorise_sigmas=winsorise_sigmas)
    return [
        fit_leaf(
            str(payload["label"]),
            [date.fromisoformat(period) for period in payload["periods"]],
            [float(value) for value in payload["values"]],
            frequency,
            horizon,
            max_folds,
            confidence_level,
            preparation,
        ).to_dict()
        for payload in payloads
    ]


def _payload(leaf: SegmentInput) -> dict[str, Any]:
    return {
        "label": leaf.label,
        "periods": [period.isoformat() for period in leaf.periods],
        "values": [float(value) for value in leaf.values],
    }


def _chunks(leaves: list[SegmentInput]) -> list[list[SegmentInput]]:
    return [leaves[i : i + FAN_OUT_CHUNK] for i in range(0, len(leaves), FAN_OUT_CHUNK)]


def dispatch(run_id: uuid.UUID, plan: GroupedPlan) -> None:
    from celery import chord

    from app.core.logging import request_id
    from app.workers.tasks import finalise_series_task, fit_series_task

    correlation = request_id.get()
    header = [
        fit_series_task.s(_chunk_job(run_id, plan, chunk), correlation).set(
            task_id=_series_task_id(run_id, index)
        )
        for index, chunk in enumerate(_chunks(plan.leaves))
    ]
    callback = finalise_series_task.s(str(run_id), correlation).set(
        task_id=_series_finalise_task_id(run_id)
    )
    chord(header)(callback)
    logger.info(
        "Run %s fanned out over %d task(s) for %d series.",
        run_id,
        len(header),
        len(plan.leaves),
    )


def cancellation_task_ids(run_id: uuid.UUID, max_series: int) -> list[str]:
    chunk_count = (max(1, max_series) + FAN_OUT_CHUNK - 1) // FAN_OUT_CHUNK
    return [
        *(_series_task_id(run_id, index) for index in range(chunk_count)),
        _series_finalise_task_id(run_id),
    ]


def _series_task_id(run_id: uuid.UUID, index: int) -> str:
    return str(uuid.uuid5(run_id, f"series-chunk:{index}"))


def _series_finalise_task_id(run_id: uuid.UUID) -> str:
    return str(uuid.uuid5(run_id, "series-finalise"))


def _chunk_job(run_id: uuid.UUID, plan: GroupedPlan, chunk: list[SegmentInput]) -> dict[str, Any]:
    return {
        "run_id": str(run_id),
        "frequency": plan.frequency.value,
        "horizon": plan.horizon,
        "max_folds": plan.max_folds,
        "confidence_level": plan.confidence_level,
        "series_total": len(plan.leaves),
        "leaves": [_payload(leaf) for leaf in chunk],
    }


def run_chunk_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    run_id = uuid.UUID(str(job["run_id"]))
    leaves = list(job["leaves"])

    fits = fit_chunk(
        leaves,
        ForecastFrequency(job["frequency"]),
        int(job["horizon"]),
        job.get("max_folds"),
        float(job["confidence_level"]),
    )

    total = int(job.get("series_total") or 0)
    counted = count_series(run_id, len(fits))
    if counted is not None and total:
        _publish_fitting(run_id, min(counted, total), total)

    return fits


def blocked_chunk(job: dict[str, Any], reason: str) -> list[dict[str, Any]]:
    rows = [
        LeafFit(label=str(leaf["label"]), blocked_reason=reason).to_dict()
        for leaf in job.get("leaves", [])
    ]

    raw_run_id = job.get("run_id")
    if raw_run_id is not None:
        try:
            run_id = uuid.UUID(str(raw_run_id))
        except ValueError:
            logger.warning("A blocked chunk carried an unusable run id: %r", raw_run_id)
            return rows

        total = int(job.get("series_total") or 0)
        counted = count_series(run_id, len(rows))
        if counted is not None and total:
            _publish_fitting(run_id, min(counted, total), total)

    return rows


async def finalise(
    run_id: uuid.UUID,
    fits: list[LeafFit],
    *,
    plan: GroupedPlan | None = None,
) -> RunStatus:
    from app.services import forecast_service

    resolved = plan or await plan_for(run_id)
    if resolved is None:
        return RunStatus.FAILED

    if not await forecast_service.checkpoint_progress(
        run_id, STORE_AT, "storing_series", "Storing the series forecasts..."
    ):
        return RunStatus.FAILED

    results = assemble_grouped(
        resolved.leaves,
        fits,
        resolved.group_by,
        np.asarray(resolved.total_path, dtype=float),
    )

    history_periods = resolved.leaves[0].periods if resolved.leaves else []

    async with session_scope() as session:
        run = await forecast_service.get_run_state(session, run_id)
        if run.status is not RunStatus.RUNNING:
            return RunStatus.FAILED
        await persist(session, run, results, resolved.forecast_periods, history_periods)

    blocked = sum(1 for row in results if row.blocked_reason)
    if blocked:
        logger.info(
            "Run %s stored %d series, %d of them apportioned.", run_id, len(results), blocked
        )

    completed = await forecast_service.complete_run(run_id)
    return RunStatus.COMPLETED if completed else RunStatus.FAILED


async def persist(
    session: AsyncSession,
    run: ForecastRun,
    results: list[SeriesResult],
    periods: list[date],
    history_periods: list[date],
) -> None:
    await session.execute(delete(ForecastSeries).where(ForecastSeries.run_id == run.id))

    by_level: dict[int, list[SeriesResult]] = {}
    for result in results:
        by_level.setdefault(result.level, []).append(result)

    rows: dict[str, ForecastSeries] = {}
    for level in sorted(by_level):
        for result in by_level[level]:
            parent = rows.get(result.parent_label) if result.parent_label else None
            row = ForecastSeries(
                run_id=run.id,
                parent_id=parent.id if parent else None,
                level=result.level,
                key=result.key,
                label=result.label,
                status=result.status,
                blocked_reason=result.blocked_reason,
                model=result.model,
                wmape=finite(result.wmape),
                mase=finite(result.mase),
                accuracy=finite(result.accuracy),
                accuracy_measured=result.accuracy_measured,
                folds=result.folds,
                forecast_total=finite(result.forecast_total) or 0.0,
                current_total=finite(result.current_total),
                prior_total=finite(result.prior_total),
                share=finite(result.share) or 0.0,
            )
            session.add(row)
            rows[result.label] = row
        await session.flush()

    below_root = [result for result in results if result.level > 0]

    session.add_all(
        [
            ForecastPoint(
                run_id=run.id,
                series_id=rows[result.label].id,
                period=period,
                kind=PointKind.FORECAST,
                forecast=finite(point),
                lower_bound=finite(low),
                upper_bound=finite(high),
            )
            for result in below_root
            for period, point, low, high in _banded(periods, result)
        ]
    )

    session.add_all(
        [
            ForecastPoint(
                run_id=run.id,
                series_id=rows[result.label].id,
                period=period,
                kind=PointKind.ACTUAL,
                actual=finite(value),
            )
            for result in below_root
            for period, value in zip(history_periods, result.history, strict=False)
        ]
    )

    run.series_count = len(results)
    await session.flush()


SORTS: dict[str, Any] = {
    "value_at_risk": (func.abs(ForecastSeries.forecast_total) * ForecastSeries.wmape).desc(),
    "wmape": ForecastSeries.wmape.desc(),
    "forecast_total": ForecastSeries.forecast_total.desc(),
    "label": ForecastSeries.label.asc(),
}
DEFAULT_SORT = "value_at_risk"
MAX_PAGE = settings.api_max_page_size


def order_terms(sort: str) -> list[Any]:
    """The ORDER BY for a requested sort, worst first, ties broken by name.

    Series that were never scored sort last, whatever the chosen order is
    measuring — except by name, where "no accuracy yet" is not a reason to come
    after Z.

    That term is left out for the name order rather than passed as a no-op. It
    was `null()`, which renders as `ORDER BY NULL`: legal in SQLite, where the
    tests run, and rejected outright by Postgres, where the product runs, with
    "non-integer constant in ORDER BY". Every request for the name order was a
    500 and nothing in the suite could see it — so this lives out here where a
    test can compile it against the dialect that actually matters.
    """
    ordering = SORTS.get(sort, SORTS[DEFAULT_SORT])
    unscored_last = sort != "label"
    return [
        *([ForecastSeries.wmape.is_(None).asc()] if unscored_last else []),
        ordering,
        ForecastSeries.label.asc(),
    ]


async def list_series(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    sort: str = DEFAULT_SORT,
    level: int | None = None,
    search: str | None = None,
    parent_id: uuid.UUID | None = None,
    status: SeriesStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ForecastSeries], int]:
    where = [ForecastSeries.run_id == run_id]
    if level is not None:
        where.append(ForecastSeries.level == level)
    if parent_id is not None:
        where.append(ForecastSeries.parent_id == parent_id)
    if status is not None:
        where.append(ForecastSeries.status == status)
    if search:
        where.append(ForecastSeries.label.ilike(f"%{search.strip()}%"))

    total = await session.scalar(select(func.count()).select_from(ForecastSeries).where(*where))

    result = await session.execute(
        select(ForecastSeries)
        .where(*where)
        .order_by(*order_terms(sort))
        .limit(max(1, min(limit, settings.api_max_page_size)))
        .offset(max(0, offset))
    )

    return list(result.scalars().all()), int(total or 0)


def _banded(
    periods: list[date],
    result: SeriesResult,
) -> list[tuple[date, float, float | None, float | None]]:
    banded = len(result.lower) == len(result.forecast) == len(result.upper)
    return [
        (
            period,
            point,
            result.lower[index] if banded else None,
            result.upper[index] if banded else None,
        )
        for index, (period, point) in enumerate(zip(periods, result.forecast, strict=False))
    ]


def _publish_fitting(run_id: uuid.UUID, done: int, total: int) -> None:
    span = FIT_TO - FIT_FROM
    progress = FIT_FROM + (span * done / total if total else span)
    _publish(
        run_id,
        progress,
        "fitting_series",
        f"Forecasting series {done:,} of {total:,}...",
    )


def _publish(run_id: uuid.UUID, progress: float, stage: str, message: str) -> None:
    publish_progress(
        ProgressEvent(
            run_id=run_id,
            status=RunStatus.RUNNING,
            progress=progress,
            stage=stage,
            message=message,
        )
    )
