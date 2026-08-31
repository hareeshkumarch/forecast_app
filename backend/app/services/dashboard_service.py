from __future__ import annotations

import uuid
from datetime import date
from typing import Final, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.numbers import compact
from app.datasets.profiler import currency_symbol, is_currency_like
from app.forecasting import decisions
from app.forecasting.hierarchy import leaf_depth
from app.forecasting.metrics import accuracy_from_wmape
from app.models.entities import (
    ForecastDriver,
    ForecastMetric,
    ForecastPoint,
    ForecastRun,
    ForecastSeries,
    Insight,
)
from app.models.enums import PointKind
from app.schemas.dashboard import (
    BreakdownRef,
    BreakdownResponse,
    BreakdownRowRead,
    DashboardQuery,
    DashboardSummary,
    DecisionAction,
    DecisionConcentration,
    DecisionHorizon,
    DecisionResponse,
    DriverResponse,
    DriverRow,
    InsightRead,
    InsightResponse,
    KpiCard,
)
from app.services import breakdown_service, forecast_service

VIEW_COLUMN: dict[str, str] = {
    "base": "forecast",
    "best": "best_case",
    "worst": "worst_case",
}


#: Distinguishes "the caller has not resolved the run" from "the caller
#: resolved it and there is none". Without it, `run=None` would mean both, and
#: a dashboard with no completed runs would re-run the lookup on every read
#: just to be told the same thing again.
_UNRESOLVED: Final = cast(ForecastRun, object())


async def _resolved(
    session: AsyncSession, query: DashboardQuery, run: ForecastRun | None
) -> ForecastRun | None:
    """The run this answer is about, looked up only if nobody has already.

    The route layer resolves it to build the cache validator (see
    `app/api/routes/dashboard.py`), so passing it back down is the difference
    between one lookup per read and two.
    """
    if run is not _UNRESOLVED:
        return run
    return await forecast_service.resolve_run(session, query.run_id)


async def revision(session: AsyncSession, run: ForecastRun | None) -> tuple[object, ...]:
    """Everything a dashboard answer for this run depends on, as a few values.

    This is what makes both the `ETag` and the read-through cache honest: an
    answer computed from this run's rows is valid exactly as long as these
    values are unchanged, so a token derived from them can key a cache entry
    that is incapable of going stale.

    What is in it, and why:

    * `updated_at` moves on every write to the run row — completion, scoring,
      cancellation, a rename.
    * `scored_at` and `scored_periods` because comparing a forecast against
      actuals writes points and metrics, and a run that has just been scored
      is a different answer with the same `id`.
    * `status`, so a run moving from running to completed cannot be served
      from whatever was cached while it was still filling in.
    * The insights' own high-water mark, because rewriting them through a
      model changes what `/insights` answers *without touching the run row* —
      the one dependency that `updated_at` alone would miss. It is one indexed
      aggregate over a handful of rows.

    One revision for all five dashboard endpoints rather than a per-endpoint
    dependency table. Rewriting insights therefore also invalidates the KPI
    cards, which do not depend on them — over-invalidation, deliberately. The
    alternative is a table of which endpoint depends on what, and the entry
    somebody gets wrong in that table is a wrong number on a screen. This way
    the mistake costs a recomputation.

    A run that does not exist has no version and no answer to cache; the empty
    tuple keeps callers from having to special-case it twice.
    """
    if run is None:
        return ()

    insights_touched = await session.scalar(
        select(func.max(Insight.updated_at)).where(Insight.run_id == run.id)
    )
    return (
        run.id,
        run.status.value,
        run.updated_at,
        run.scored_at,
        run.scored_periods,
        insights_touched,
    )


def format_value(
    value: float, *, unit: str = "absolute", currency: bool = True, symbol: str = "$"
) -> str:
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "percentage_points":
        return f"{value:+.1f}pp"
    if unit == "count":
        return f"{value:,.0f}"

    return compact(value, currency=currency, symbol=symbol)


async def _metrics(session: AsyncSession, run_id: uuid.UUID) -> dict[str, ForecastMetric]:
    result = await session.execute(select(ForecastMetric).where(ForecastMetric.run_id == run_id))
    return {metric.name: metric for metric in result.scalars().all()}


async def _scenario_total(
    session: AsyncSession, run_id: uuid.UUID, view: str, start: date | None, end: date | None
) -> float:
    column = getattr(ForecastPoint, VIEW_COLUMN.get(view, "forecast"))
    statement = select(column).where(
        ForecastPoint.run_id == run_id,
        ForecastPoint.series_id.is_(None),
        ForecastPoint.kind == PointKind.FORECAST,
    )
    if start is not None:
        statement = statement.where(ForecastPoint.period >= start)
    if end is not None:
        statement = statement.where(ForecastPoint.period <= end)

    result = await session.execute(statement)
    return float(sum(value for (value,) in result.all() if value is not None))


async def summary(
    session: AsyncSession, query: DashboardQuery, *, run: ForecastRun | None = _UNRESOLVED
) -> DashboardSummary:
    run = await _resolved(session, query, run)
    if run is None:
        return DashboardSummary(
            run_id=None,
            dataset_id=None,
            run_name=None,
            selected_model=None,
            generated_at=None,
            range_start=query.start,
            range_end=query.end,
            kpis=[],
            has_data=False,
        )

    metrics = await _metrics(session, run.id)
    currency = _is_currency(run.target_column)
    symbol = _symbol_for(run.target_column)

    forecast_total = await _scenario_total(session, run.id, query.view, query.start, query.end)
    best_total = await _scenario_total(session, run.id, "best", query.start, query.end)
    worst_total = await _scenario_total(session, run.id, "worst", query.start, query.end)

    actual_total = await _actual_total(session, run.id, run, query.start)

    prior_ytd = await _prior_year_actual_total(session, run.id, run)

    accuracy = metrics.get("accuracy")
    wmape = metrics.get("wmape")

    cards: list[KpiCard] = [
        _card(
            key="total_forecast",
            label="Total Forecast",
            value=forecast_total,
            currency=currency,
            symbol=symbol,
            comparison=(
                previous.previous_value
                if (previous := metrics.get("forecast_total")) is not None
                else None
            ),
            comparison_label="vs previous run",
            higher_is_better=True,
        ),
        _card(
            key="actual_ytd",
            label="Actual YTD",
            value=actual_total,
            currency=currency,
            symbol=symbol,
            comparison=prior_ytd,
            comparison_label=_actual_window_label(run),
            higher_is_better=True,
            label_describes_the_window=True,
        ),
        _accuracy_card(run, accuracy),
        _error_card(run, wmape),
        _card(
            key="best_case",
            label="Best Case",
            value=best_total,
            currency=currency,
            symbol=symbol,
            comparison=forecast_total,
            comparison_label="vs base case",
            higher_is_better=True,
        ),
        _card(
            key="worst_case",
            label="Worst Case",
            value=worst_total,
            currency=currency,
            symbol=symbol,
            comparison=forecast_total,
            comparison_label="vs base case",
            higher_is_better=True,
        ),
    ]

    return DashboardSummary(
        run_id=run.id,
        dataset_id=run.dataset_id,
        run_name=run.name,
        selected_model=run.selected_model,
        generated_at=run.completed_at or run.created_at,
        range_start=query.start or run.forecast_start,
        range_end=query.end or run.forecast_end,
        kpis=cards,
        has_data=True,
        currency_symbol=symbol if currency else "",
        breakdowns=[
            BreakdownRef(
                column=ref.column,
                label=ref.label,
                source=ref.source,
                cardinality=ref.cardinality,
            )
            for ref in await breakdown_service.available(session, run)
        ],
    )


def _ytd_window(run: ForecastRun) -> tuple[date | None, date | None]:
    if run.history_end is None:
        return None, None
    return date(run.history_end.year, 1, 1), run.history_end


async def _actual_total(
    session: AsyncSession, run_id: uuid.UUID, run: ForecastRun, start: date | None
) -> float:
    ytd_start, ytd_end = _ytd_window(run)
    lower = start or ytd_start

    statement = select(ForecastPoint.actual).where(
        ForecastPoint.run_id == run_id,
        ForecastPoint.series_id.is_(None),
        ForecastPoint.kind == PointKind.ACTUAL,
    )
    if lower is not None:
        statement = statement.where(ForecastPoint.period >= lower)
    if ytd_end is not None:
        statement = statement.where(ForecastPoint.period <= ytd_end)

    result = await session.execute(statement)
    return float(sum(value for (value,) in result.all() if value is not None))


async def _prior_year_actual_total(
    session: AsyncSession, run_id: uuid.UUID, run: ForecastRun
) -> float | None:
    start, end = _ytd_window(run)
    if start is None or end is None:
        return None

    prior_start = date(start.year - 1, 1, 1)
    prior_end = date(end.year - 1, end.month, end.day)

    if run.history_start and prior_start < run.history_start:
        return None

    result = await session.execute(
        select(ForecastPoint.actual).where(
            ForecastPoint.run_id == run_id,
            ForecastPoint.series_id.is_(None),
            ForecastPoint.kind == PointKind.ACTUAL,
            ForecastPoint.period >= prior_start,
            ForecastPoint.period <= prior_end,
        )
    )
    total = sum(value for (value,) in result.all() if value is not None)
    return float(total) if total else None


def _actual_window_label(run: ForecastRun) -> str:
    start, end = _ytd_window(run)
    if start and end:
        return f"{start:%b %Y} – {end:%b %Y}"  # noqa: RUF001
    return "historical actuals"


def _error_card(run: ForecastRun, backtest: ForecastMetric | None) -> KpiCard:
    if run.realized_wmape is not None:
        return _card(
            key="weighted_mape",
            label="Actual Error",
            value=run.realized_wmape,
            unit="percent",
            currency=False,
            comparison=backtest.value if backtest else None,
            comparison_label="vs expected",
            higher_is_better=False,
        )

    return _card(
        key="weighted_mape",
        label="Expected Error",
        value=backtest.value if backtest else float("nan"),
        unit="percent",
        currency=False,
        comparison=backtest.previous_value if backtest else None,
        comparison_label="vs previous run",
        higher_is_better=False,
    )


def _accuracy_card(run: ForecastRun, backtest: ForecastMetric | None) -> KpiCard:
    if run.realized_wmape is not None:
        return _card(
            key="forecast_accuracy",
            label="Actual Accuracy",
            value=accuracy_from_wmape(run.realized_wmape),
            unit="percent",
            currency=False,
            comparison=backtest.value if backtest else None,
            comparison_label="vs expected",
            higher_is_better=True,
        )

    return _card(
        key="forecast_accuracy",
        label="Expected Accuracy",
        value=backtest.value if backtest else float("nan"),
        unit="percent",
        currency=False,
        comparison=backtest.previous_value if backtest else None,
        comparison_label="vs previous run",
        higher_is_better=True,
    )


def _card(
    *,
    key: str,
    label: str,
    value: float,
    currency: bool,
    comparison: float | None,
    comparison_label: str,
    higher_is_better: bool,
    unit: str = "absolute",
    symbol: str = "$",
    label_describes_the_window: bool = False,
) -> KpiCard:
    """Build one KPI card.

    `comparison_label` normally names what the delta is measured against ("vs
    previous run"), and is dropped when there is no delta — a first run has no
    previous one, and a caption pointing at a comparison nobody made reads as a
    card that failed to load. Set `label_describes_the_window` where the caption
    stands on its own, like the date range under Actual YTD.
    """
    import math

    safe_value = value if math.isfinite(value) else 0.0
    delta: float | None = None
    delta_display: str | None = None
    direction = "flat"
    tone = "neutral"

    if comparison is not None and math.isfinite(comparison) and comparison != 0:
        if unit == "percent":
            delta = safe_value - comparison
            delta_display = f"{delta:+.1f} pts"
        else:
            delta = (safe_value - comparison) / abs(comparison) * 100.0
            delta_display = f"{delta:+.1f}%"

        if abs(delta) < 0.05:
            direction, tone = "flat", "neutral"
        else:
            rising = delta > 0
            direction = "up" if rising else "down"

            tone = "positive" if rising == higher_is_better else "negative"

    return KpiCard(
        key=key,
        label=label,
        value=round(safe_value, 4),
        display_value=(
            format_value(safe_value, unit=unit, currency=currency, symbol=symbol)
            if math.isfinite(value)
            else "—"
        ),
        unit=unit,
        comparison_value=comparison,
        comparison_label=(
            comparison_label if label_describes_the_window or delta_display is not None else None
        ),
        delta=round(delta, 3) if delta is not None else None,
        delta_display=delta_display,
        direction=direction,
        tone=tone,
    )


async def drivers(
    session: AsyncSession, query: DashboardQuery, *, run: ForecastRun | None = _UNRESOLVED
) -> DriverResponse:
    run = await _resolved(session, query, run)
    if run is None:
        return DriverResponse(run_id=None, rows=[])

    result = await session.execute(
        select(ForecastDriver).where(ForecastDriver.run_id == run.id).order_by(ForecastDriver.rank)
    )
    return DriverResponse(
        run_id=run.id, rows=[DriverRow.model_validate(row) for row in result.scalars().all()]
    )


async def insights(
    session: AsyncSession,
    query: DashboardQuery,
    *,
    limit: int = 20,
    run: ForecastRun | None = _UNRESOLVED,
) -> InsightResponse:
    run = await _resolved(session, query, run)
    if run is None:
        return InsightResponse(run_id=None, items=[])

    result = await session.execute(
        select(Insight).where(Insight.run_id == run.id).order_by(Insight.rank).limit(limit)
    )
    return InsightResponse(
        run_id=run.id, items=[InsightRead.model_validate(row) for row in result.scalars().all()]
    )


async def decision(
    session: AsyncSession, query: DashboardQuery, *, run: ForecastRun | None = _UNRESOLVED
) -> DecisionResponse:
    run = await _resolved(session, query, run)
    if run is None:
        return DecisionResponse(run_id=None)

    periods = await _forecast_periods(session, run.id, query.start, query.end)
    metrics = await _metrics(session, run.id)

    backtested = metrics.get("accuracy")
    realized = None if run.realized_wmape is None else accuracy_from_wmape(run.realized_wmape)
    # A scored run beats a backtest: it grades this forecast, not the method.
    accuracy = realized if realized is not None else (backtested.value if backtested else None)

    found = decisions.decide(
        periods,
        frequency=run.frequency,
        confidence_level=run.confidence_level,
        accuracy=accuracy,
        at_risk=await _value_at_risk(session, run),
        realized_bias=run.realized_bias,
        realized_wmape=run.realized_wmape,
        realized_coverage=run.realized_coverage,
    )
    if found is None:
        return DecisionResponse(run_id=run.id)

    currency = _is_currency(run.target_column)
    symbol = _symbol_for(run.target_column)

    def shown(value: float) -> str:
        return compact(value, currency=currency, symbol=symbol)

    return DecisionResponse(
        run_id=run.id,
        has_decision=True,
        grade=found.grade.value,
        meaning=found.meaning,
        accuracy=found.accuracy,
        confidence_level=found.confidence_level,
        commit=found.commit,
        base=found.base,
        prepare=found.prepare,
        spread_pct=found.spread_pct,
        commit_display=shown(found.commit),
        base_display=shown(found.base),
        prepare_display=shown(found.prepare),
        exposure=found.exposure,
        downside_pct=found.downside_pct,
        lean_pct=found.lean_pct,
        horizon=DecisionHorizon(
            periods=found.horizon.periods,
            through=found.horizon.through,
            covers_run=found.horizon.covers_run,
        ),
        concentration=(
            None
            if found.concentration is None
            else DecisionConcentration(
                count=found.concentration.count,
                total=found.concentration.total,
                share=found.concentration.share,
                leaders=found.concentration.leaders,
                lopsided=found.concentration.lopsided,
            )
        ),
        actions=[
            DecisionAction(headline=action.headline, detail=action.detail)
            for action in found.actions
        ],
    )


async def _forecast_periods(
    session: AsyncSession, run_id: uuid.UUID, start: date | None, end: date | None
) -> list[decisions.Period]:
    statement = (
        select(ForecastPoint)
        .where(
            ForecastPoint.run_id == run_id,
            ForecastPoint.series_id.is_(None),
            ForecastPoint.kind == PointKind.FORECAST,
            ForecastPoint.forecast.is_not(None),
        )
        .order_by(ForecastPoint.period)
    )
    if start is not None:
        statement = statement.where(ForecastPoint.period >= start)
    if end is not None:
        statement = statement.where(ForecastPoint.period <= end)

    result = await session.execute(statement)
    return [
        decisions.Period(
            period=point.period,
            forecast=float(point.forecast or 0.0),
            lower=None if point.lower_bound is None else float(point.lower_bound),
            upper=None if point.upper_bound is None else float(point.upper_bound),
            worst=None if point.worst_case is None else float(point.worst_case),
        )
        for point in result.scalars().all()
    ]


async def _value_at_risk(session: AsyncSession, run: ForecastRun) -> list[tuple[str, float]]:
    leaves = leaf_depth(run.group_by)
    if leaves == 0:
        return []

    result = await session.execute(
        select(ForecastSeries.label, ForecastSeries.forecast_total, ForecastSeries.wmape).where(
            ForecastSeries.run_id == run.id,
            ForecastSeries.level == leaves,
            ForecastSeries.wmape.is_not(None),
        )
    )
    return [
        (label, abs(float(total)) * float(wmape) / 100.0)
        for label, total, wmape in result.all()
        if total is not None and wmape is not None
    ]


def _is_currency(column: str) -> bool:
    return is_currency_like(column)


def _symbol_for(column: str) -> str:
    return currency_symbol(column) or settings.currency_symbol


async def breakdown(
    session: AsyncSession,
    query: DashboardQuery,
    column: str,
    *,
    run: ForecastRun | None = _UNRESOLVED,
) -> BreakdownResponse:
    run = await _resolved(session, query, run)
    if run is None:
        return BreakdownResponse(
            run_id=None, column=column, label=column, source="", currency=False, total=0.0
        )

    built = await breakdown_service.build(session, run, column)
    return BreakdownResponse(
        run_id=run.id,
        column=built.column,
        label=built.label,
        source=built.source,
        currency=built.currency,
        total=built.total,
        rows=[
            BreakdownRowRead(
                label=row.label,
                forecast=row.forecast,
                share=row.share,
                prior=row.prior,
                change=row.change,
                accuracy=row.accuracy,
                accuracy_measured=row.accuracy_measured,
                actual=row.actual,
            )
            for row in built.rows
        ],
    )
