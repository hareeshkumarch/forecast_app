from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    CategoryForecast,
    ForecastDriver,
    ForecastMetric,
    ForecastPoint,
    ForecastRun,
    Insight,
    RegionalForecast,
)
from app.models.enums import PointKind
from app.schemas.dashboard import (
    CategoryResponse,
    CategoryRow,
    DashboardQuery,
    DashboardSummary,
    DriverResponse,
    DriverRow,
    InsightRead,
    InsightResponse,
    KpiCard,
    RegionResponse,
    RegionRow,
)
from app.services import forecast_service

VIEW_COLUMN: dict[str, str] = {
    "base": "forecast",
    "best": "best_case",
    "worst": "worst_case",
}


def format_value(value: float, *, unit: str = "absolute", currency: bool = True) -> str:
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "percentage_points":
        return f"{value:+.1f}pp"
    if unit == "count":
        return f"{value:,.0f}"

    prefix = "$" if currency else ""
    sign = "-" if value < 0 else ""
    magnitude = abs(value)

    if magnitude >= 1_000_000_000:
        return f"{sign}{prefix}{magnitude / 1_000_000_000:.2f}B"
    if magnitude >= 1_000_000:
        return f"{sign}{prefix}{magnitude / 1_000_000:.2f}M"
    if magnitude >= 1_000:
        return f"{sign}{prefix}{magnitude / 1_000:.1f}K"
    return f"{sign}{prefix}{magnitude:,.0f}"


async def _metrics(session: AsyncSession, run_id: uuid.UUID) -> dict[str, ForecastMetric]:
    result = await session.execute(select(ForecastMetric).where(ForecastMetric.run_id == run_id))
    return {metric.name: metric for metric in result.scalars().all()}


async def _scenario_total(
    session: AsyncSession, run_id: uuid.UUID, view: str, start: date | None, end: date | None
) -> float:
    column = getattr(ForecastPoint, VIEW_COLUMN.get(view, "forecast"))
    statement = select(column).where(
        ForecastPoint.run_id == run_id, ForecastPoint.kind == PointKind.FORECAST
    )
    if start is not None:
        statement = statement.where(ForecastPoint.period >= start)
    if end is not None:
        statement = statement.where(ForecastPoint.period <= end)

    result = await session.execute(statement)
    return float(sum(value for (value,) in result.all() if value is not None))


async def summary(session: AsyncSession, query: DashboardQuery) -> DashboardSummary:
    run = await forecast_service.resolve_run(session, query.run_id)
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
            comparison=metrics.get("forecast_total").previous_value if "forecast_total" in metrics else None,
            comparison_label="vs previous run",
            higher_is_better=True,
        ),
        _card(
            key="actual_ytd",
            label="Actual YTD",
            value=actual_total,
            currency=currency,
            comparison=prior_ytd,
            comparison_label=_actual_window_label(run),
            higher_is_better=True,
        ),
        _card(
            key="forecast_accuracy",
            label="Forecast Accuracy",
            value=accuracy.value if accuracy else float("nan"),
            unit="percent",
            currency=False,
            comparison=accuracy.previous_value if accuracy else None,
            comparison_label="vs previous run",
            higher_is_better=True,
        ),
        _card(
            key="weighted_mape",
            label="Weighted MAPE",
            value=wmape.value if wmape else float("nan"),
            unit="percent",
            currency=False,
            comparison=wmape.previous_value if wmape else None,
            comparison_label="vs previous run",

            higher_is_better=False,
        ),
        _card(
            key="best_case",
            label="Best Case",
            value=best_total,
            currency=currency,
            comparison=forecast_total,
            comparison_label="vs base case",
            higher_is_better=True,
        ),
        _card(
            key="worst_case",
            label="Worst Case",
            value=worst_total,
            currency=currency,
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
        ForecastPoint.run_id == run_id, ForecastPoint.kind == PointKind.ACTUAL
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
) -> KpiCard:
    import math

    safe_value = value if math.isfinite(value) else 0.0
    delta: float | None = None
    delta_display: str | None = None
    direction = "flat"
    tone = "neutral"

    if comparison is not None and math.isfinite(comparison) and comparison != 0:
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
            format_value(safe_value, unit=unit, currency=currency)
            if math.isfinite(value)
            else "—"
        ),
        unit=unit,
        comparison_value=comparison,
        comparison_label=comparison_label,
        delta=round(delta, 3) if delta is not None else None,
        delta_display=delta_display,
        direction=direction,
        tone=tone,
    )


async def regions(session: AsyncSession, query: DashboardQuery) -> RegionResponse:
    run = await forecast_service.resolve_run(session, query.run_id)
    if run is None:
        return RegionResponse(run_id=None, rows=[], total=0.0)

    result = await session.execute(
        select(RegionalForecast)
        .where(RegionalForecast.run_id == run.id)
        .order_by(RegionalForecast.forecast_value.desc())
    )
    rows = [RegionRow.model_validate(row) for row in result.scalars().all()]
    return RegionResponse(
        run_id=run.id, rows=rows, total=round(sum(r.forecast_value for r in rows), 4)
    )


async def categories(session: AsyncSession, query: DashboardQuery) -> CategoryResponse:
    run = await forecast_service.resolve_run(session, query.run_id)
    if run is None:
        return CategoryResponse(run_id=None, rows=[], total=0.0, total_display="—")

    result = await session.execute(
        select(CategoryForecast)
        .where(CategoryForecast.run_id == run.id)
        .order_by(CategoryForecast.rank)
    )
    rows = [CategoryRow.model_validate(row) for row in result.scalars().all()]
    total = sum(r.forecast_value for r in rows)

    return CategoryResponse(
        run_id=run.id,
        rows=rows,
        total=round(total, 4),
        total_display=format_value(total, currency=_is_currency(run.target_column)),
    )


async def drivers(session: AsyncSession, query: DashboardQuery) -> DriverResponse:
    run = await forecast_service.resolve_run(session, query.run_id)
    if run is None:
        return DriverResponse(run_id=None, rows=[])

    result = await session.execute(
        select(ForecastDriver).where(ForecastDriver.run_id == run.id).order_by(ForecastDriver.rank)
    )
    return DriverResponse(
        run_id=run.id, rows=[DriverRow.model_validate(row) for row in result.scalars().all()]
    )


async def insights(session: AsyncSession, query: DashboardQuery, *, limit: int = 20) -> InsightResponse:
    run = await forecast_service.resolve_run(session, query.run_id)
    if run is None:
        return InsightResponse(run_id=None, items=[])

    result = await session.execute(
        select(Insight).where(Insight.run_id == run.id).order_by(Insight.rank).limit(limit)
    )
    return InsightResponse(
        run_id=run.id, items=[InsightRead.model_validate(row) for row in result.scalars().all()]
    )


def _is_currency(column: str) -> bool:
    words = ("revenue", "sales", "amount", "value", "spend", "cost", "price", "gmv", "bookings")
    lowered = column.lower()
    return any(word in lowered for word in words)
