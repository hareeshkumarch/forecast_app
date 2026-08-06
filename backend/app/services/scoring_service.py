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

#: Aggregations under which a combination that recorded nothing in a period
#: genuinely measured zero. Under the others — a mean, a closing balance — an
#: absent row means the value is unknown, and scoring it as zero would invent
#: a miss out of missing data.
ZERO_IS_AN_OBSERVATION = frozenset({MeasureAggregation.SUM})

#: When a candidate file's account of the run's history counts as a different
#: series. Not a tuned threshold: 1.0 is the point at which the two series
#: differ by more than the whole of the smaller one, so they agree with nothing
#: better than they agree with each other.
DISAGREES_ENTIRELY = 1.0

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


@dataclass(slots=True)
class SourceChoice:
    """Which file will settle a run's horizon, and what was turned away."""

    dataset: Dataset | None = None
    #: Files that cover the horizon and hold the run's columns, but describe a
    #: different series over the history the run was fitted on. Counted rather
    #: than dropped silently: "nothing covers this yet" and "three files cover
    #: it and none of them is your data" call for different actions.
    contradicting: int = 0


async def choose_source(session: AsyncSession, run: ForecastRun) -> SourceChoice:
    """
    The newest dataset that can say what happened over this run's horizon.

    Two tests, and the second is the one that keeps the answer honest.

    A dataset **qualifies** when it holds the columns the run was built on and
    its calendar reaches into the forecast. That much is derived from the run
    rather than configured — anything narrower would be a guess about how a
    particular customer names their files.

    But `date` and `sales` are what half the world calls its columns, so
    qualifying is not the same as being the same data. A qualifying file is
    also **checked against the run's own history**: aggregate it exactly as the
    run aggregated, over the periods they share, and see whether it tells the
    same story. A refreshed file does, near enough — a restatement moves a few
    percent. Last quarter's EMEA numbers set against a freshly uploaded APAC
    file do not, and grading against one would report a wildly wrong accuracy
    with total confidence.

    A file that shares no history with the run cannot be checked either way —
    a file holding only the new periods is a perfectly ordinary thing to
    upload — so it is kept as a fallback rather than trusted first.
    """
    if run.forecast_start is None:
        return SourceChoice()

    history = await _run_history(session, run.id)

    result = await session.execute(
        select(Dataset)
        .where(Dataset.parquet_path.is_not(None))
        # The id breaks ties: several datasets uploaded in the same clock tick
        # are equally new, and without a second key the same run could pick a
        # different source each time it was scored.
        .order_by(Dataset.created_at.desc(), Dataset.id.desc())
    )

    # Whittled down before any file is opened. Reaching past the forecast is
    # the one test the profile can settle on its own.
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
    """
    Read the candidate files in turn and say which one holds this run's data.

    Gives back the first file that agrees with the run's history, the first
    that shares no history to be judged on, and how many contradict it — as
    positions in `paths`, so the ORM objects stay on the thread that owns them.

    One connection for the whole batch. Opening an in-memory database costs
    several times what a query this small costs to run, and there is a
    candidate file for every upload a customer has ever made, so the naive
    version spent nine tenths of its time opening and closing databases.
    """
    chosen: int | None = None
    unproven: int | None = None
    contradicting = 0

    with queries.connect() as connection:
        for index, path in enumerate(paths):
            if not path.exists():
                continue
            try:
                columns = set(queries.column_names(path, connection=connection))
            except Exception as exc:  # a file that cannot be read cannot score
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
                # Nothing shared to judge it on. Newest first, so the first one
                # here is the one to fall back to.
                unproven = index if unproven is None else unproven
            elif disagreement < DISAGREES_ENTIRELY:
                chosen = index
                break
            else:
                contradicting += 1

    return chosen, unproven, contradicting


async def candidate_source(session: AsyncSession, run: ForecastRun) -> Dataset | None:
    """The dataset `choose_source` settled on, for callers that only want it."""
    return (await choose_source(session, run)).dataset


async def _run_history(session: AsyncSession, run_id: uuid.UUID) -> dict[date, float]:
    """The run's own top line over the history it was fitted on."""
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
    """
    How far a file's account of the run's history is from the run's own.

    Scaled by the smaller of the two totals, which is what makes it symmetric:
    a file ten times the size and a file a tenth of it are equally not this
    data, and dividing by the run's history alone would wave the small one
    through. `None` means they share no period, so there is nothing to judge.
    """
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
        # Both say nothing happened. They agree, but about nothing — there is
        # no evidence here either way.
        return None
    if min(ours, theirs) == 0.0:
        # One of them records zero across every period they share while the
        # other records something. That is not a small disagreement.
        return math.inf

    gap = sum(abs(history[period] - observed.totals[period]) for period in shared)
    return gap / min(ours, theirs)


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

    if dataset_id is not None:
        # Named explicitly, so it is the caller's judgement rather than ours.
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
    """Why there is no source, in terms of what the reader can do about it."""
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
