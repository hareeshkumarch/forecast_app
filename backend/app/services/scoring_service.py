"""
What the forecast turned out to be worth.

Every accuracy figure the platform reported before this one came from a
backtest: folds held out of the history the model was fitted on. That is the
model's expected error and it is a genuinely useful number, but it is not the
error the forecast turned out to have. The two come apart exactly when it
matters — a regime change, a promotion, a lost customer — because a backtest
can only ever be surprised by the past.

This scores a finished run against actuals that arrived after it ran, which is
the only number a planner can hold a forecast to.

Two rules keep the answer honest:

* **Whole periods only.** A month's forecast measured against eleven days of
  actuals reports a collapse that never happened, and nothing downstream can
  tell that apart from a real one.
* **Say what could not be scored.** A pooled tail, a series that appeared after
  the run, a period still in progress — each is reported as itself rather than
  quietly folded in as a miss.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

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
from app.models.enums import MeasureAggregation, PointKind, RunStatus

logger = get_logger(__name__)

#: Aggregations under which a combination that recorded nothing in a period
#: genuinely measured zero. Under the others — a mean, a closing balance — an
#: absent row means the value is unknown, and scoring it as zero would invent
#: a miss out of missing data.
ZERO_IS_AN_OBSERVATION = frozenset({MeasureAggregation.SUM})

NO_FORECAST = "This series stored no forecast for a period that has finished."
POOLED = "A pooled tail stands for many combinations and matches none of them."
NOT_RECORDED = "The source recorded nothing here, and this run does not sum."


@dataclass(slots=True)
class SeriesScore:
    """One series' realized error, or the reason it has none."""

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
    """How a run's forecast compares with what actually happened."""

    run_id: uuid.UUID
    scored_at: datetime | None = None
    source_dataset_id: uuid.UUID | None = None
    source_dataset_name: str | None = None

    #: The periods the run forecast, how many the source can settle, and how
    #: many are still being lived through. The last are real forecasts that
    #: nobody can grade yet, not failures.
    horizon: int = 0
    scored_periods: int = 0
    pending_periods: int = 0
    #: The last date the source carries — what decides which periods are done.
    covered_through: date | None = None

    forecast_total: float = 0.0
    actual_total: float = 0.0
    wmape: float | None = None
    mae: float | None = None
    #: Signed, as a share of actual: whether the forecast ran high or low.
    #: A different fault from being far out, and it needs a different fix.
    bias: float | None = None
    #: The share of actuals that landed inside the interval. An 80% interval
    #: that catches 40% of them is not an 80% interval.
    coverage: float | None = None
    confidence_level: float | None = None

    #: Combinations the source recorded that the run never forecast. They land
    #: in the top line's actual but in no leaf's, which is the reason to count
    #: them rather than let the levels quietly disagree.
    unforecast_keys: int = 0

    series: list[SeriesScore] = field(default_factory=list)
    #: Set when nothing could be scored, in the caller's language.
    blocked_reason: str | None = None

    @property
    def scored(self) -> bool:
        return self.scored_periods > 0

    @property
    def accuracy_percent(self) -> float | None:
        """The realized counterpart of the accuracy every run already reports."""
        return None if self.wmape is None else _finite(accuracy_from_wmape(self.wmape))


# ------------------------------------------------------------- finding actuals


async def candidate_source(session: AsyncSession, run: ForecastRun) -> Dataset | None:
    """
    The newest dataset that could say what happened over this run's horizon.

    Derived from the run rather than configured: a dataset qualifies when it
    holds the columns the run was built on and its calendar reaches into the
    forecast. That is the whole test — anything narrower would be a guess about
    how a particular customer names their files.
    """
    if run.forecast_start is None:
        return None

    needed = {run.time_column, run.target_column, *(run.group_by or [])}
    result = await session.execute(
        select(Dataset)
        .where(Dataset.parquet_path.is_not(None))
        # The id breaks ties: several datasets uploaded in the same clock tick
        # are equally new, and without a second key the same run could pick a
        # different source each time it was scored.
        .order_by(Dataset.created_at.desc(), Dataset.id.desc())
    )

    for dataset in result.scalars():
        if dataset.date_range_end is None or dataset.date_range_end < run.forecast_start:
            continue
        if needed.issubset(await _columns_of(dataset)):
            return dataset

    return None


async def _columns_of(dataset: Dataset) -> set[str]:
    path = Path(dataset.parquet_path or "")
    if not path.exists():
        return set()
    try:
        return set(await asyncio.to_thread(queries.column_names, path))
    except Exception as exc:  # a file that cannot be read simply cannot score
        logger.warning("Could not read the columns of dataset %s: %s", dataset.id, exc)
        return set()


# --------------------------------------------------------------------- scoring


async def score_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    dataset_id: uuid.UUID | None = None,
) -> Scorecard:
    """
    Compares a finished run with actuals and stores the result.

    Re-scoring is expected rather than exceptional: a horizon settles a period
    at a time, so the same run is worth scoring again every time more data
    lands. Each run overwrites the last.
    """
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

    source = (
        await dataset_service.get_dataset(session, dataset_id)
        if dataset_id is not None
        else await candidate_source(session, run)
    )
    if source is None:
        card.blocked_reason = (
            "No dataset yet covers the period this run forecast. Upload data that "
            f"reaches past {horizon[0].isoformat()}."
        )
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
    """The run's own line: the number on the dashboard, graded."""
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
    """Every series in the tree, each against the actuals its own key selects."""
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

    # A leaf's actual is the combination it names; a parent's is every
    # combination beneath it, which is that key one level shorter. Indexing
    # every prefix once turns each series' lookup into a dictionary hit rather
    # than a scan over the whole panel.
    prefixed: dict[tuple[str, ...], dict[date, float]] = {}
    for key, series in observed.by_key.items():
        for depth in range(len(key) + 1):
            bucket = prefixed.setdefault(key[:depth], {})
            for period, value in series.items():
                bucket[period] = bucket.get(period, 0.0) + value

    # A pooled tail stands for many combinations at once, so with one present
    # there is no telling an unforecast combination from a pooled one.
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

        # The root *is* the run's own line — it stores no curve of its own,
        # because a second copy of the top line is what `persist` avoids
        # writing. Taking the figures already computed for that line is both
        # cheaper than redoing them and the only way the two cannot disagree.
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
    """Writes a score onto the series it belongs to, ungraded included."""
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
    """Why this series cannot be graded, or None when it can."""
    if not scoped:
        return NO_FORECAST

    key = _key_of(row, group_by)
    if queries.POOLED_KEY in key:
        return POOLED

    # Under a sum, nothing recorded is a real zero — the shop sold none. Under
    # a mean or a closing balance it is simply unknown, and calling it zero
    # would manufacture a miss.
    if key not in prefixed and not absent_is_zero:
        return NOT_RECORDED

    return None


def _key_of(row: ForecastSeries, group_by: list[str]) -> tuple[str, ...]:
    """A series' key as the prefix tuple the observed keys are indexed by."""
    key = row.key or {}
    return tuple(str(key.get(column, queries.MISSING_KEY)) for column in group_by[: row.level])


def _by_period(point: ForecastPoint) -> date:
    return point.period


# --------------------------------------------------------------------- storage


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
    """
    The last score computed for a run, without recomputing it.

    A run that has never been scored comes back with the reason and, where one
    exists, the dataset that would settle it — so the caller can offer the
    action rather than only report its absence.
    """
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
        candidate = await candidate_source(session, run)
        card.blocked_reason = (
            f"Not scored yet — '{candidate.name}' now covers this horizon."
            if candidate
            else "Not scored yet — no dataset covers the period this run forecast."
        )
        card.source_dataset_id = candidate.id if candidate else None
        card.source_dataset_name = candidate.name if candidate else None

    return card


async def _stored_series(session: AsyncSession, run_id: uuid.UUID) -> list[SeriesScore]:
    """
    The per-series scores as they were written, so reading a scorecard back
    gives what computing it gave. The reason a series went ungraded is not
    stored — only that it did — because the row itself says why: an
    apportioned series has no error to compare against.
    """
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
    """None rather than nan: a metric with no denominator has no value."""
    return float(value) if np.isfinite(value) else None
