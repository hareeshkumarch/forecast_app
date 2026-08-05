"""
Grouped runs: forecasting every series in a run's grain rather than one total.

The top line is fitted first, by `forecast_service`, because it is the number
every level has to add up to. This module then fits each leaf in its own right
— in parallel where there is somewhere to fan out to — assembles the tree and
stores it.

A 500-series panel costs roughly four and a half minutes fitted one leaf at a
time (measured: 554 ms per leaf), which is what makes the fan-out worth its
machinery.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, func, null, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
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
from app.models.entities import ForecastPoint, ForecastRun, ForecastSeries
from app.models.enums import ForecastFrequency, MeasureAggregation, PointKind, RunStatus
from app.services.job_runner import ProgressEvent, executors, publish_progress
from app.services.progress_relay import count_series, forget_series_count

logger = get_logger(__name__)

# One leaf costs about half a second, so ten of them is a task of a few seconds
# — long enough that the broker round trip disappears into it, short enough
# that a worker lost mid-chunk repeats very little.
FAN_OUT_CHUNK = 10

# Where the series work sits in the run's progress bar. The top line and its
# insights are done by the time this starts.
FIT_FROM, FIT_TO = 0.68, 0.94
STORE_AT = 0.96


@dataclass(slots=True)
class GroupedPlan:
    """Everything the tree needs except the leaf fits themselves."""

    leaves: list[SegmentInput]
    group_by: list[str]
    frequency: ForecastFrequency
    horizon: int
    max_folds: int | None
    confidence_level: float
    total_path: list[float]
    forecast_periods: list[date]


async def plan_for(run_id: uuid.UUID) -> GroupedPlan | None:
    """
    Rebuilds a grouped run's leaves and the total they must add up to.

    Derived rather than carried. The dataset file does not change once
    uploaded and the aggregation is deterministic, so a worker holding nothing
    but a run id reconstructs exactly what the dispatcher saw — and the panel
    never has to travel through the broker to reach the callback that
    assembles it.
    """
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
    # The window the aggregation settled on, so the recent slice matches the
    # totals it reported rather than a second, differently-sized guess.
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
    """The run's own forecast, read back from the points already stored for it."""
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
    """
    Forecasts every series in a grouped run.

    Returns RUNNING when the work has been handed to a chord — the run is then
    finished by `finalise`, on whichever worker runs the callback. Returns
    COMPLETED when the leaves were fitted here.
    """
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
    """
    Fits every leaf without a broker, spreading chunks over the process pool
    so a single-node deployment still uses more than one core.
    """
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
) -> list[dict[str, Any]]:
    """
    Fits a chunk of leaves. Runs in a pool worker or a Celery task, so it takes
    and returns plain data and never raises for a single bad series.
    """
    return [
        fit_leaf(
            str(payload["label"]),
            [date.fromisoformat(period) for period in payload["periods"]],
            [float(value) for value in payload["values"]],
            frequency,
            horizon,
            max_folds,
            confidence_level,
        ).to_dict()
        for payload in payloads
    ]


def _payload(leaf: SegmentInput) -> dict[str, Any]:
    """Only the history crosses the wire, because only the history is fitted."""
    return {
        "label": leaf.label,
        "periods": [period.isoformat() for period in leaf.periods],
        "values": [float(value) for value in leaf.values],
    }


def _chunks(leaves: list[SegmentInput]) -> list[list[SegmentInput]]:
    return [leaves[i : i + FAN_OUT_CHUNK] for i in range(0, len(leaves), FAN_OUT_CHUNK)]


def dispatch(run_id: uuid.UUID, plan: GroupedPlan) -> None:
    """
    Hands the leaf fits to the workers as a chord: a group of chunk tasks, and
    a callback that assembles what they return.

    A chord rather than waiting on a group, because blocking inside a task for
    other tasks to finish deadlocks as soon as the pool is busy with the very
    work being waited on.
    """
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
    """Every deterministic child id a bounded grouped run can create."""
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
    """One task's worth of work, as JSON the broker can carry."""
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
    """
    A chunk task's whole body: fit the leaves, then say how far the run has got.

    The count lives in Redis because a chunk knows only its own leaves, and the
    bar has to move for the minutes a large panel takes.
    """
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
    """
    Stands in for a chunk that could not be fitted at all.

    Every series in it is returned blocked so the tree still knows they exist:
    they are apportioned from their parent, the levels still add up, and each
    row carries the reason rather than quietly going missing.
    """
    rows = [
        LeafFit(label=str(leaf["label"]), blocked_reason=reason).to_dict()
        for leaf in job.get("leaves", [])
    ]
    run_id = uuid.UUID(str(job["run_id"]))
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
    """
    Assembles the tree from the fits, stores it, and completes the run.

    Called inline on a single node, and by the chord callback otherwise; the
    plan is rebuilt when it was not carried across.
    """
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

    # Every leaf shares one calendar, which is what lets the levels be summed.
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
    """Writes the tree and one forecast curve per node, parents before children."""
    await session.execute(delete(ForecastSeries).where(ForecastSeries.run_id == run.id))

    by_level: dict[int, list[SeriesResult]] = {}
    for result in results:
        by_level.setdefault(result.level, []).append(result)

    rows: dict[str, ForecastSeries] = {}
    # A level at a time: children need their parent's id, but siblings do not
    # need each other's, so one flush per level rather than one per series.
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
                wmape=result.wmape,
                accuracy=result.accuracy,
                accuracy_measured=result.accuracy_measured,
                folds=result.folds,
                forecast_total=result.forecast_total,
                current_total=result.current_total,
                prior_total=result.prior_total,
                share=result.share,
            )
            session.add(row)
            rows[result.label] = row
        await session.flush()

    # The root is reconciled to the run's own forecast by construction, so a
    # curve for it would be a second copy of the top line — one that exports
    # and charts would then have to know to ignore.
    below_root = [result for result in results if result.level > 0]

    session.add_all(
        [
            ForecastPoint(
                run_id=run.id,
                series_id=rows[result.label].id,
                period=period,
                kind=PointKind.FORECAST,
                forecast=point,
                # Empty where the series was apportioned rather than fitted, so
                # a chart draws no band instead of inventing one.
                lower_bound=low,
                upper_bound=high,
            )
            for result in below_root
            for period, point, low, high in _banded(periods, result)
        ]
    )

    # Its own past, so a chart scoped to one series has something to hang the
    # horizon on rather than three points floating in space.
    session.add_all(
        [
            ForecastPoint(
                run_id=run.id,
                series_id=rows[result.label].id,
                period=period,
                kind=PointKind.ACTUAL,
                actual=value,
            )
            for result in below_root
            for period, value in zip(history_periods, result.history, strict=False)
        ]
    )

    run.series_count = len(results)
    await session.flush()


# How the triage list can be ordered. Value at risk is the default because it
# is the only one that answers "what should I look at first": a big series
# forecast badly costs more than a small one forecast worse.
SORTS: dict[str, Any] = {
    "value_at_risk": (func.abs(ForecastSeries.forecast_total) * ForecastSeries.wmape).desc(),
    "wmape": ForecastSeries.wmape.desc(),
    "forecast_total": ForecastSeries.forecast_total.desc(),
    "label": ForecastSeries.label.asc(),
}
DEFAULT_SORT = "value_at_risk"
MAX_PAGE = 200


async def list_series(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    sort: str = DEFAULT_SORT,
    level: int | None = None,
    search: str | None = None,
    parent_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ForecastSeries], int]:
    """
    A page of a run's series, and how many there are in total.

    A series with no measured error has no value at risk to rank on, so those
    sort last however the list is ordered: an unknown is not evidence of a
    problem, and burying the measured ones behind them would defeat the point.
    """
    where = [ForecastSeries.run_id == run_id]
    if level is not None:
        where.append(ForecastSeries.level == level)
    if parent_id is not None:
        where.append(ForecastSeries.parent_id == parent_id)
    if search:
        where.append(ForecastSeries.label.ilike(f"%{search.strip()}%"))

    total = await session.scalar(select(func.count()).select_from(ForecastSeries).where(*where))

    ordering = SORTS.get(sort, SORTS[DEFAULT_SORT])
    result = await session.execute(
        select(ForecastSeries)
        .where(*where)
        .order_by(
            # NULLS LAST is not portable across SQLite and Postgres, so the
            # nullness is ordered explicitly first.
            ForecastSeries.wmape.is_(None).asc() if sort != "label" else null(),
            ordering,
            ForecastSeries.label.asc(),
        )
        .limit(max(1, min(limit, MAX_PAGE)))
        .offset(max(0, offset))
    )

    return list(result.scalars().all()), int(total or 0)


def _banded(
    periods: list[date],
    result: SeriesResult,
) -> list[tuple[date, float, float | None, float | None]]:
    """Pairs each forecast period with its bounds, or with none where there are none."""
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
