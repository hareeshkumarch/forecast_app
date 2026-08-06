from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.datasets import queries
from app.models.entities import CategoryForecast, ForecastRun, ForecastSeries, RegionalForecast

FROM_SERIES = "series"
FROM_REGION = "region"
FROM_CATEGORY = "category"


@dataclass(slots=True)
class BreakdownRef:
    column: str
    label: str
    source: str
    cardinality: int


@dataclass(slots=True)
class BreakdownRow:
    label: str
    forecast: float
    share: float
    prior: float | None = None
    change: float | None = None
    accuracy: float | None = None
    accuracy_measured: bool = False
    actual: float | None = None


@dataclass(slots=True)
class Breakdown:
    column: str
    label: str
    source: str
    currency: bool
    total: float = 0.0
    rows: list[BreakdownRow] = field(default_factory=list)


def humanise(column: str) -> str:
    words = column.replace("_", " ").replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else column


async def available(session: AsyncSession, run: ForecastRun) -> list[BreakdownRef]:
    grain = [str(column) for column in (run.group_by or [])]
    refs: list[BreakdownRef] = []

    if grain:
        counts = await _grain_cardinality(session, run.id, grain)
        refs += [
            BreakdownRef(
                column=column,
                label=humanise(column),
                source=FROM_SERIES,
                cardinality=counts.get(column, 0),
            )
            for column in grain
            if counts.get(column, 0) > 1
        ]

    seen = {ref.column for ref in refs}
    for column, source, model in (
        (run.region_column, FROM_REGION, RegionalForecast),
        (run.category_column, FROM_CATEGORY, CategoryForecast),
    ):
        if not column or column in seen:
            continue
        count = await session.scalar(
            select(model.id).where(model.run_id == run.id).limit(1)  # type: ignore[attr-defined]
        )
        if count is not None:
            refs.append(
                BreakdownRef(column=column, label=humanise(column), source=source, cardinality=0)
            )
            seen.add(column)

    return refs


async def _grain_cardinality(
    session: AsyncSession, run_id: uuid.UUID, grain: list[str]
) -> dict[str, int]:
    leaves = await _leaves(session, run_id, len(grain))
    counts: dict[str, set[str]] = {column: set() for column in grain}
    for leaf in leaves:
        for column in grain:
            value = (leaf.key or {}).get(column)
            if value is not None:
                counts[column].add(str(value))
    return {column: len(values) for column, values in counts.items()}


async def _leaves(session: AsyncSession, run_id: uuid.UUID, depth: int) -> list[ForecastSeries]:
    result = await session.execute(
        select(ForecastSeries).where(ForecastSeries.run_id == run_id, ForecastSeries.level == depth)
    )
    return list(result.scalars().all())


async def build(session: AsyncSession, run: ForecastRun, column: str) -> Breakdown:
    from app.datasets.profiler import is_currency_like

    refs = {ref.column: ref for ref in await available(session, run)}
    ref = refs.get(column)
    if ref is None:
        offered = ", ".join(sorted(refs)) or "none"
        raise ValidationError(
            f"This forecast cannot be broken down by '{column}'. Available: {offered}."
        )

    breakdown = Breakdown(
        column=column,
        label=ref.label,
        source=ref.source,
        currency=is_currency_like(run.target_column),
    )

    if ref.source == FROM_SERIES:
        breakdown.rows = await _from_series(session, run, column)
    elif ref.source == FROM_REGION:
        breakdown.rows = await _from_regions(session, run.id)
    else:
        breakdown.rows = await _from_categories(session, run.id)

    breakdown.total = round(sum(row.forecast for row in breakdown.rows), 4)
    if breakdown.total:
        for row in breakdown.rows:
            row.share = round(row.forecast / breakdown.total * 100.0, 2)

    breakdown.rows.sort(key=lambda row: row.forecast, reverse=True)
    return breakdown


async def _from_series(session: AsyncSession, run: ForecastRun, column: str) -> list[BreakdownRow]:
    grain = [str(name) for name in (run.group_by or [])]
    leaves = await _leaves(session, run.id, len(grain))

    forecast: dict[str, float] = defaultdict(float)
    prior: dict[str, float] = defaultdict(float)
    actual: dict[str, float] = defaultdict(float)
    scored: dict[str, bool] = defaultdict(bool)
    error_weight: dict[str, float] = defaultdict(float)
    error_total: dict[str, float] = defaultdict(float)

    for leaf in leaves:
        value = (leaf.key or {}).get(column)
        if value is None:
            continue
        name = str(value)
        if name == queries.POOLED_KEY:
            continue

        forecast[name] += leaf.forecast_total
        if leaf.prior_total is not None:
            prior[name] += leaf.prior_total
        if leaf.realized_actual_total is not None:
            actual[name] += leaf.realized_actual_total
            scored[name] = True
        if leaf.wmape is not None:
            weight = abs(leaf.forecast_total)
            error_weight[name] += weight
            error_total[name] += leaf.wmape * weight

    rows: list[BreakdownRow] = []
    for name, total in forecast.items():
        measured = error_weight[name] > 0
        was = prior.get(name)
        rows.append(
            BreakdownRow(
                label=name,
                forecast=round(total, 4),
                share=0.0,
                prior=round(was, 4) if was else None,
                change=round((total - was) / abs(was) * 100.0, 2) if was else None,
                accuracy=(
                    round(max(0.0, 100.0 - error_total[name] / error_weight[name]), 2)
                    if measured
                    else None
                ),
                accuracy_measured=measured,
                actual=round(actual[name], 4) if scored[name] else None,
            )
        )
    return rows


async def _from_regions(session: AsyncSession, run_id: uuid.UUID) -> list[BreakdownRow]:
    result = await session.execute(
        select(RegionalForecast).where(RegionalForecast.run_id == run_id)
    )
    return [
        BreakdownRow(
            label=row.region,
            forecast=row.forecast_value,
            share=row.share or 0.0,
            prior=row.prior_year_value,
            change=row.change_vs_last_year,
            accuracy=row.accuracy,
            accuracy_measured=row.accuracy_measured,
        )
        for row in result.scalars().all()
    ]


async def _from_categories(session: AsyncSession, run_id: uuid.UUID) -> list[BreakdownRow]:
    result = await session.execute(
        select(CategoryForecast).where(CategoryForecast.run_id == run_id)
    )
    return [
        BreakdownRow(
            label=row.category,
            forecast=row.forecast_value,
            share=row.share,
            change=row.change_vs_last_year,
            accuracy=row.accuracy,
            accuracy_measured=row.accuracy_measured,
        )
        for row in result.scalars().all()
    ]
