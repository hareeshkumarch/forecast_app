from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.core.numbers import finite
from app.datasets import queries
from app.forecasting.frequency import period_end, period_is_settled
from app.forecasting.metrics import accuracy_from_wmape, mae, wmape
from app.models.entities import Dataset, ForecastPoint, ForecastRun, ForecastSeries
from app.models.enums import ForecastFrequency, MeasureAggregation, PointKind, RunStatus

logger = get_logger(__name__)

ZERO_IS_AN_OBSERVATION = frozenset({MeasureAggregation.SUM})

DISAGREES_ENTIRELY = 1.0

NO_FORECAST = "This series stored no forecast for a period that has finished."
POOLED = "A pooled tail stands for many combinations and matches none of them."
NOT_RECORDED = "The source recorded nothing here, and this run does not sum."


@dataclass(slots=True)
class SeriesScore:
    series_id: uuid.UUID
    label: str
    level: int
    forecast_total: float
    actual_total: float | None = None
    wmape: float | None = None
    scored_periods: int = 0
    unscored_reason: str | None = None


@dataclass(slots=True)
class Scorecard:
    run_id: uuid.UUID
    scored_at: datetime | None = None
    source_dataset_id: uuid.UUID | None = None
    source_dataset_name: str | None = None

    horizon: int = 0
    scored_periods: int = 0
    pending_periods: int = 0
    covered_through: date | None = None

    forecast_total: float = 0.0
    actual_total: float = 0.0
    wmape: float | None = None
    mae: float | None = None
    bias: float | None = None
    coverage: float | None = None
    confidence_level: float | None = None

    unforecast_keys: int = 0

    series: list[SeriesScore] = field(default_factory=list)
    blocked_reason: str | None = None

    @property
    def scored(self) -> bool:
        return self.scored_periods > 0

    @property
    def accuracy_percent(self) -> float | None:
        return None if self.wmape is None else _finite(accuracy_from_wmape(self.wmape))


@dataclass(slots=True)
class SourceChoice:
    dataset: Dataset | None = None
    contradicting: int = 0


async def choose_source(session: AsyncSession, run: ForecastRun) -> SourceChoice:
    if run.forecast_start is None:
        return SourceChoice()

    history = await _run_history(session, run.id)

    result = await session.execute(
        select(Dataset)
        .where(Dataset.parquet_path.is_not(None))
        .order_by(Dataset.created_at.desc(), Dataset.id.desc())
    )

    candidates = [
        dataset
        for dataset in result.scalars()
        if dataset.date_range_end is not None and dataset.date_range_end >= run.forecast_start
    ]
    if not candidates:
        return SourceChoice()

    chosen, unproven, contradicting = await asyncio.to_thread(
        _weigh_candidates,
        [Path(dataset.parquet_path or "") for dataset in candidates],
        needed=frozenset({run.time_column, run.target_column, *(run.group_by or [])}),
        history=history,
        time_column=run.time_column,
        target_column=run.target_column,
        frequency=run.frequency,
        aggregation=run.aggregation,
    )

    settled = chosen if chosen is not None else unproven
    return SourceChoice(
        dataset=None if settled is None else candidates[settled],
        contradicting=contradicting,
    )


def _weigh_candidates(
    paths: list[Path],
    *,
    needed: frozenset[str],
    history: dict[date, float],
    time_column: str,
    target_column: str,
    frequency: ForecastFrequency,
    aggregation: MeasureAggregation,
) -> tuple[int | None, int | None, int]:
    chosen: int | None = None
    unproven: int | None = None
    contradicting = 0

    with queries.connect() as connection:
        for index, path in enumerate(paths):
            if not path.exists():
                continue
            try:
                columns = set(queries.column_names(path, connection=connection))
            except Exception as exc:
                logger.warning("Could not read the columns of %s: %s", path, exc)
                continue
            if not needed.issubset(columns):
                continue

            disagreement = _disagreement_with_history(
                path,
                history=history,
                time_column=time_column,
                target_column=target_column,
                frequency=frequency,
                aggregation=aggregation,
                connection=connection,
            )
            if disagreement is None:
                unproven = index if unproven is None else unproven
            elif disagreement < DISAGREES_ENTIRELY:
                chosen = index
                break
            else:
                contradicting += 1

    return chosen, unproven, contradicting


async def candidate_source(session: AsyncSession, run: ForecastRun) -> Dataset | None:
    return (await choose_source(session, run)).dataset


async def _run_history(session: AsyncSession, run_id: uuid.UUID) -> dict[date, float]:
    result = await session.execute(
        select(ForecastPoint).where(
            ForecastPoint.run_id == run_id,
            ForecastPoint.kind == PointKind.ACTUAL,
            ForecastPoint.series_id.is_(None),
        )
    )
    return {
        point.period: float(point.actual) for point in result.scalars() if point.actual is not None
    }


def _disagreement_with_history(
    path: Path,
    *,
    history: dict[date, float],
    time_column: str,
    target_column: str,
    frequency: ForecastFrequency,
    aggregation: MeasureAggregation,
    connection: duckdb.DuckDBPyConnection,
) -> float | None:
    if not history:
        return None

    periods = sorted(history)
    observed = queries.observed_window(
        path,
        time_column,
        target_column,
        frequency,
        start=periods[0],
        end=period_end(periods[-1], frequency),
        aggregation=aggregation,
        connection=connection,
    )

    shared = [period for period in periods if period in observed.totals]
    if not shared:
        return None

    ours = sum(abs(history[period]) for period in shared)
    theirs = sum(abs(observed.totals[period]) for period in shared)

    if ours == 0.0 and theirs == 0.0:
        return None
    if min(ours, theirs) == 0.0:
        return math.inf

    gap = sum(abs(history[period] - observed.totals[period]) for period in shared)
    return gap / min(ours, theirs)


async def _columns_of(dataset: Dataset) -> set[str]:
    path = Path(dataset.parquet_path or "")
    if not path.exists():
        return set()
    try:
        return set(await asyncio.to_thread(queries.column_names, path))
    except Exception as exc:
        logger.warning("Could not read the columns of dataset %s: %s", dataset.id, exc)
        return set()


async def score_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    dataset_id: uuid.UUID | None = None,
) -> Scorecard:
    from app.services import dataset_service, forecast_service

    run = await forecast_service.get_run(session, run_id)
    if run.status is not RunStatus.COMPLETED:
        raise ValidationError("Only a completed run can be scored against actuals.")

    card = Scorecard(run_id=run.id, confidence_level=run.confidence_level)

    points = await _forecast_points(session, run_id)
    top_line = sorted(
        (point for point in points if point.series_id is None), key=lambda point: point.period
    )
    horizon = sorted({point.period for point in top_line})
    card.horizon = len(horizon)
    card.pending_periods = card.horizon
    if not horizon:
        card.blocked_reason = "This run stored no forecast to score."
        return card

    if dataset_id is not None:
        source: Dataset | None = await dataset_service.get_dataset(session, dataset_id)
        choice = SourceChoice(dataset=source)
    else:
        choice = await choose_source(session, run)
        source = choice.dataset

    if source is None:
        clause = _nothing_to_score_against(choice, horizon[0])
        card.blocked_reason = clause[:1].upper() + clause[1:]
        return card

    parquet_path = Path(source.parquet_path or "")
    if not parquet_path.exists():
        raise ValidationError(f"Dataset '{source.name}' no longer has a stored file to read.")

    missing = {run.time_column, run.target_column, *(run.group_by or [])} - await _columns_of(
        source
    )
    if missing:
        raise ValidationError(
            f"Dataset '{source.name}' is missing {', '.join(sorted(missing))}, "
            "so it cannot be compared with this run."
        )

    card.source_dataset_id = source.id
    card.source_dataset_name = source.name
    group_by = [str(column) for column in (run.group_by or [])]

    observed = await asyncio.to_thread(
        queries.observed_window,
        parquet_path,
        run.time_column,
        run.target_column,
        run.frequency,
        start=horizon[0],
        end=period_end(horizon[-1], run.frequency),
        group_columns=group_by or None,
        aggregation=run.aggregation,
    )
    card.covered_through = observed.covered_through

    reach = observed.covered_through
    settled = [
        period
        for period in horizon
        if reach is not None and period_is_settled(period, reach, run.frequency)
    ]
    card.scored_periods = len(settled)
    card.pending_periods = card.horizon - card.scored_periods

    if not settled:
        card.blocked_reason = (
            f"'{source.name}' reaches {reach.isoformat() if reach else 'no further than this run'}"
            f", which does not complete any of the {card.horizon} period(s) it forecast."
        )
        await _store(session, run, card)
        return card

    _score_top_line(card, top_line, observed.totals, set(settled))
    if group_by:
        await _score_series(session, card, run, points, observed, set(settled), group_by)

    await _store(session, run, card)
    logger.info(
        "Scored run %s over %d of %d period(s) against '%s': wMAPE %s",
        run.id,
        card.scored_periods,
        card.horizon,
        source.name,
        f"{card.wmape:.2f}%" if card.wmape is not None else "not measurable",
    )
    return card


def _score_top_line(
    card: Scorecard,
    top_line: list[ForecastPoint],
    totals: dict[date, float],
    settled: set[date],
) -> None:
    rows = [point for point in top_line if point.period in settled]
    if not rows:
        return

    actuals = np.array([totals.get(row.period, 0.0) for row in rows], dtype=float)
    predicted = np.array([row.forecast or 0.0 for row in rows], dtype=float)

    for row, actual in zip(rows, actuals, strict=True):
        row.actual = float(actual)

    card.forecast_total = float(np.sum(predicted))
    card.actual_total = float(np.sum(actuals))
    card.wmape = _finite(wmape(actuals, predicted))
    card.mae = _finite(mae(actuals, predicted))

    scale = float(np.sum(np.abs(actuals)))
    if scale > 0:
        card.bias = float(np.sum(predicted - actuals) / scale * 100.0)

    inside = [
        row.lower_bound <= actual <= row.upper_bound
        for row, actual in zip(rows, actuals, strict=True)
        if row.lower_bound is not None and row.upper_bound is not None
    ]
    if inside:
        card.coverage = float(sum(inside) / len(inside) * 100.0)


async def _score_series(
    session: AsyncSession,
    card: Scorecard,
    run: ForecastRun,
    points: list[ForecastPoint],
    observed: queries.ObservedWindow,
    settled: set[date],
    group_by: list[str],
) -> None:
    result = await session.execute(
        select(ForecastSeries)
        .where(ForecastSeries.run_id == run.id)
        .order_by(ForecastSeries.level, ForecastSeries.label)
    )
    rows = list(result.scalars().all())
    if not rows:
        return

    by_series: dict[uuid.UUID, list[ForecastPoint]] = {}
    for point in points:
        if point.series_id is not None and point.period in settled:
            by_series.setdefault(point.series_id, []).append(point)

    prefixed: dict[tuple[str, ...], dict[date, float]] = {}
    for key, series in observed.by_key.items():
        for depth in range(len(key) + 1):
            bucket = prefixed.setdefault(key[:depth], {})
            for period, value in series.items():
                bucket[period] = bucket.get(period, 0.0) + value

    pooled = any(queries.POOLED_KEY in _key_of(row, group_by) for row in rows)
    if not pooled:
        forecast_keys = {_key_of(row, group_by) for row in rows if row.level == len(group_by)}
        card.unforecast_keys = len(set(observed.by_key) - forecast_keys)

    absent_is_zero = run.aggregation in ZERO_IS_AN_OBSERVATION

    for row in rows:
        score = SeriesScore(
            series_id=row.id,
            label=row.label,
            level=row.level,
            forecast_total=row.forecast_total,
        )

        if row.level == 0:
            score.actual_total = card.actual_total
            score.wmape = card.wmape
            score.scored_periods = card.scored_periods
            _remember(row, score)
            card.series.append(score)
            continue

        scoped = sorted(by_series.get(row.id, []), key=_by_period)
        reason = _unscorable(row, group_by, scoped, prefixed, absent_is_zero)
        if reason is not None:
            score.unscored_reason = reason
            _remember(row, score)
            card.series.append(score)
            continue

        actual_by_period = prefixed.get(_key_of(row, group_by), {})
        actuals = np.array([actual_by_period.get(p.period, 0.0) for p in scoped], dtype=float)
        predicted = np.array([point.forecast or 0.0 for point in scoped], dtype=float)

        for point, actual in zip(scoped, actuals, strict=True):
            point.actual = float(actual)

        score.actual_total = float(np.sum(actuals))
        score.wmape = _finite(wmape(actuals, predicted))
        score.scored_periods = len(scoped)
        _remember(row, score)
        card.series.append(score)


def _remember(row: ForecastSeries, score: SeriesScore) -> None:
    row.scored_periods = score.scored_periods
    row.realized_wmape = finite(score.wmape)
    row.realized_actual_total = finite(score.actual_total)


def _unscorable(
    row: ForecastSeries,
    group_by: list[str],
    scoped: list[ForecastPoint],
    prefixed: dict[tuple[str, ...], dict[date, float]],
    absent_is_zero: bool,
) -> str | None:
    if not scoped:
        return NO_FORECAST

    key = _key_of(row, group_by)
    if queries.POOLED_KEY in key:
        return POOLED

    if key not in prefixed and not absent_is_zero:
        return NOT_RECORDED

    return None


def _key_of(row: ForecastSeries, group_by: list[str]) -> tuple[str, ...]:
    key = row.key or {}
    return tuple(str(key.get(column, queries.MISSING_KEY)) for column in group_by[: row.level])


def _by_period(point: ForecastPoint) -> date:
    return point.period


async def _forecast_points(session: AsyncSession, run_id: uuid.UUID) -> list[ForecastPoint]:
    result = await session.execute(
        select(ForecastPoint).where(
            ForecastPoint.run_id == run_id, ForecastPoint.kind == PointKind.FORECAST
        )
    )
    return list(result.scalars().all())


async def _store(session: AsyncSession, run: ForecastRun, card: Scorecard) -> None:
    run.scored_at = datetime.now(UTC)
    run.scored_dataset_id = card.source_dataset_id
    run.scored_periods = card.scored_periods
    run.scored_through = card.covered_through
    run.realized_wmape = finite(card.wmape)
    run.realized_mae = finite(card.mae)
    run.realized_bias = finite(card.bias)
    run.realized_coverage = finite(card.coverage)
    card.scored_at = run.scored_at
    await session.flush()


async def stored_scorecard(session: AsyncSession, run_id: uuid.UUID) -> Scorecard:
    from app.services import forecast_service

    run = await forecast_service.get_run(session, run_id)
    card = Scorecard(
        run_id=run.id,
        scored_at=run.scored_at,
        source_dataset_id=run.scored_dataset_id,
        scored_periods=run.scored_periods,
        covered_through=run.scored_through,
        wmape=run.realized_wmape,
        mae=run.realized_mae,
        bias=run.realized_bias,
        coverage=run.realized_coverage,
        confidence_level=run.confidence_level,
    )

    points = await _forecast_points(session, run_id)
    top_line = [point for point in points if point.series_id is None]
    card.horizon = len({point.period for point in top_line})
    card.pending_periods = max(card.horizon - card.scored_periods, 0)
    card.forecast_total = float(sum(point.forecast or 0.0 for point in top_line))
    card.actual_total = float(sum(point.actual or 0.0 for point in top_line))

    if run.scored_dataset_id is not None:
        source = await session.get(Dataset, run.scored_dataset_id)
        card.source_dataset_name = source.name if source else None

    if run.scored_at is not None:
        card.series = await _stored_series(session, run_id)

    if run.scored_at is None:
        choice = await choose_source(session, run)
        card.blocked_reason = (
            f"Not scored yet — '{choice.dataset.name}' now covers this horizon."
            if choice.dataset
            else f"Not scored yet — {_nothing_to_score_against(choice, run.forecast_start)}"
        )
        card.source_dataset_id = choice.dataset.id if choice.dataset else None
        card.source_dataset_name = choice.dataset.name if choice.dataset else None

    return card


def _nothing_to_score_against(choice: SourceChoice, from_period: date | None) -> str:
    if choice.contradicting:
        one = choice.contradicting == 1
        return (
            f"{choice.contradicting} uploaded file{'' if one else 's'} cover"
            f"{'s' if one else ''} these periods but describe"
            f"{'s' if one else ''} different figures over the history this run was "
            "built on, so grading against "
            f"{'it' if one else 'them'} would not compare like with like. "
            "Upload a refresh of the data this run used."
        )

    reach = f" that reaches past {from_period.isoformat()}" if from_period else ""
    return f"no dataset yet covers the period this run forecast. Upload data{reach}."


async def _stored_series(session: AsyncSession, run_id: uuid.UUID) -> list[SeriesScore]:
    result = await session.execute(
        select(ForecastSeries)
        .where(ForecastSeries.run_id == run_id)
        .order_by(ForecastSeries.level, ForecastSeries.label)
    )
    return [
        SeriesScore(
            series_id=row.id,
            label=row.label,
            level=row.level,
            forecast_total=row.forecast_total,
            actual_total=row.realized_actual_total,
            wmape=row.realized_wmape,
            scored_periods=row.scored_periods,
            unscored_reason=(
                None if row.scored_periods else row.blocked_reason or "This series was not graded."
            ),
        )
        for row in result.scalars().all()
    ]


def _finite(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None
