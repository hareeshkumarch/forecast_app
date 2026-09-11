from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.forecasting.diagnostics import profile_series
from app.forecasting.metric_plan import MetricPlan, evaluate_plan, plan_for
from app.models.entities import ForecastPoint
from app.models.enums import ForecastFrequency, PointKind
from app.services import forecast_service

MIN_RESIDUALS = 4

HISTOGRAM_BINS = 11


@dataclass(slots=True, frozen=True)
class Residual:
    period: date
    actual: float
    predicted: float
    residual: float

    def as_dict(self) -> dict[str, object]:
        return {
            "period": self.period.isoformat(),
            "actual": round(self.actual, 4),
            "predicted": round(self.predicted, 4),
            "residual": round(self.residual, 4),
        }


@dataclass(slots=True, frozen=True)
class Bucket:
    start: float
    end: float
    count: int

    def as_dict(self) -> dict[str, object]:
        return {"start": round(self.start, 4), "end": round(self.end, 4), "count": self.count}


@dataclass(slots=True)
class DiagnosticReport:
    run_id: uuid.UUID
    series_id: uuid.UUID | None
    frequency: ForecastFrequency
    plan: MetricPlan
    scored: dict[str, float]
    residuals: list[Residual] = field(default_factory=list)
    histogram: list[Bucket] = field(default_factory=list)
    residual_sigma: float | None = None
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": str(self.run_id),
            "series_id": str(self.series_id) if self.series_id else None,
            "frequency": self.frequency.value,
            "plan": self.plan.as_dict(),
            "scored": {name: _finite(value) for name, value in self.scored.items()},
            "residuals": [row.as_dict() for row in self.residuals],
            "histogram": [bucket.as_dict() for bucket in self.histogram],
            "residual_sigma": _finite(self.residual_sigma),
            "caveats": list(self.caveats),
        }


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return round(number, 6) if np.isfinite(number) else None


def pair(points: list[ForecastPoint]) -> list[Residual]:
    rows: list[Residual] = []
    for point in points:
        actual, predicted = point.actual, point.forecast
        if actual is None or predicted is None:
            continue
        if not (np.isfinite(actual) and np.isfinite(predicted)):
            continue
        rows.append(
            Residual(
                period=point.period,
                actual=float(actual),
                predicted=float(predicted),
                residual=float(predicted) - float(actual),
            )
        )
    rows.sort(key=lambda row: row.period)
    return rows


def histogram(residuals: list[Residual], bins: int = HISTOGRAM_BINS) -> list[Bucket]:
    if len(residuals) < MIN_RESIDUALS:
        return []

    values = np.array([row.residual for row in residuals], dtype=float)
    reach = float(np.max(np.abs(values)))
    if reach <= 0:
        return []

    edges = np.linspace(-reach, reach, bins + 1)
    counts, _ = np.histogram(values, bins=edges)
    return [
        Bucket(start=float(edges[index]), end=float(edges[index + 1]), count=int(count))
        for index, count in enumerate(counts)
    ]


async def build(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    series_id: uuid.UUID | None = None,
) -> DiagnosticReport | None:
    run = await forecast_service.get_run(session, run_id)
    points = await forecast_service.points_for_run(session, run_id, series_id=series_id)
    if not points:
        return None

    residuals = pair(points)

    history = np.array(
        [p.actual for p in points if p.actual is not None and np.isfinite(p.actual)],
        dtype=float,
    )
    profile = profile_series(history, run.frequency) if history.size else None
    plan = plan_for(profile)

    caveats: list[str] = []
    if not residuals:
        caveats.append(
            "No period has both a forecast and an outcome yet, so there is nothing to score."
        )
        return DiagnosticReport(
            run_id=run_id,
            series_id=series_id,
            frequency=run.frequency,
            plan=plan,
            scored={},
            caveats=caveats,
        )

    actual = np.array([row.actual for row in residuals], dtype=float)
    predicted = np.array([row.predicted for row in residuals], dtype=float)

    fitted_periods = {row.period for row in residuals}
    insample = np.array(
        [
            p.actual
            for p in points
            if p.kind is PointKind.ACTUAL
            and p.period not in fitted_periods
            and p.actual is not None
            and np.isfinite(p.actual)
        ],
        dtype=float,
    )
    if insample.size == 0:
        insample = history

    scored = evaluate_plan(plan, actual, predicted, insample=insample)

    if len(residuals) < MIN_RESIDUALS:
        caveats.append(
            f"{len(residuals)} scored period(s): too few to read a shape from, so the "
            "distribution and the autocorrelation are withheld."
        )

    sigma = float(np.std(np.array([row.residual for row in residuals], dtype=float)))

    return DiagnosticReport(
        run_id=run_id,
        series_id=series_id,
        frequency=run.frequency,
        plan=plan,
        scored=scored,
        residuals=residuals,
        histogram=histogram(residuals),
        residual_sigma=sigma,
        caveats=caveats,
    )
