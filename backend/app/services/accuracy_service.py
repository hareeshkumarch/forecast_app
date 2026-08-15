from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.provenance import Provenance
from app.core.provenance import current as current_provenance
from app.forecasting.calibration import (
    COVERAGE_TOLERANCE_PP,
    MIN_COVERAGE_SAMPLE,
    CoverageReport,
    Interval,
    realised_coverage,
)
from app.forecasting.metrics import forecast_value_add, relative_bias, wmape
from app.forecasting.routing import BASELINE_MODELS
from app.models.entities import ForecastPoint, ForecastRun, ForecastSeries, ModelCandidate
from app.models.enums import PointKind

MIN_RUNS_FOR_HEADLINE = 3
MIN_PERIODS_FOR_HEADLINE = 26


@dataclass(slots=True)
class HorizonAccuracy:
    horizon: int
    wape: float | None
    bias_pct: float | None
    observations: int

    def as_dict(self) -> dict[str, object]:
        return {
            "horizon": self.horizon,
            "wape": _round(self.wape),
            "bias_pct": _round(self.bias_pct),
            "observations": self.observations,
        }


@dataclass(slots=True)
class ClassAccuracy:
    demand_class: str
    wape: float | None
    bias_pct: float | None
    series: int
    point_forecast_claimed: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "demand_class": self.demand_class,
            "wape": _round(self.wape),
            "bias_pct": _round(self.bias_pct),
            "series": self.series,
            "point_forecast_claimed": self.point_forecast_claimed,
        }


@dataclass(slots=True)
class ValueAdd:
    model: str
    model_error: float | None
    baseline: str | None
    baseline_error: float | None
    improvement_pct: float | None

    @property
    def beats_baseline(self) -> bool:
        return self.improvement_pct is not None and self.improvement_pct > 0

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "model_error": _round(self.model_error),
            "baseline": self.baseline,
            "baseline_error": _round(self.baseline_error),
            "improvement_pct": _round(self.improvement_pct),
            "beats_baseline": self.beats_baseline,
        }


@dataclass(slots=True)
class AccuracyReport:
    run_id: UUID
    dataset_id: UUID
    as_of: datetime | None
    provenance: Provenance
    backtest: dict[str, object]
    by_horizon: list[HorizonAccuracy] = field(default_factory=list)
    by_class: list[ClassAccuracy] = field(default_factory=list)
    coverage: list[dict[str, object]] = field(default_factory=list)
    value_add: ValueAdd | None = None
    caveats: list[str] = field(default_factory=list)

    @property
    def measured_against_outcomes(self) -> bool:
        return self.as_of is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": str(self.run_id),
            "dataset_id": str(self.dataset_id),
            "scored_at": self.as_of.isoformat() if self.as_of else None,
            "measured_against_outcomes": self.measured_against_outcomes,
            "provenance": self.provenance.as_dict(),
            "backtest": self.backtest,
            "by_horizon": [row.as_dict() for row in self.by_horizon],
            "by_class": [row.as_dict() for row in self.by_class],
            "coverage": self.coverage,
            "coverage_tolerance_pp": COVERAGE_TOLERANCE_PP,
            "forecast_value_add": self.value_add.as_dict() if self.value_add else None,
            "caveats": list(self.caveats),
        }


def _round(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), 4)


def horizon_accuracy(points: list[ForecastPoint]) -> list[HorizonAccuracy]:
    scored = [p for p in points if p.actual is not None and p.forecast is not None]
    if not scored:
        return []

    step_of = {period: step for step, period in enumerate(sorted({p.period for p in scored}), 1)}
    by_step: dict[int, list[ForecastPoint]] = {}
    for point in scored:
        by_step.setdefault(step_of[point.period], []).append(point)

    rows: list[HorizonAccuracy] = []
    for step in sorted(by_step):
        members = by_step[step]
        actual = np.array([p.actual for p in members], dtype=float)
        predicted = np.array([p.forecast for p in members], dtype=float)
        rows.append(
            HorizonAccuracy(
                horizon=step,
                wape=_finite(wmape(actual, predicted)),
                bias_pct=_finite(relative_bias(actual, predicted)),
                observations=len(members),
            )
        )
    return rows


def class_accuracy(series: list[ForecastSeries]) -> list[ClassAccuracy]:
    grouped: dict[str, list[ForecastSeries]] = {}
    for row in series:
        demand_class = _demand_class_of(row)
        grouped.setdefault(demand_class, []).append(row)

    rows: list[ClassAccuracy] = []
    for demand_class in sorted(grouped):
        members = grouped[demand_class]
        errors = [r.realized_wmape for r in members if r.realized_wmape is not None]
        rows.append(
            ClassAccuracy(
                demand_class=demand_class,
                wape=float(np.mean(errors)) if errors else None,
                bias_pct=None,
                series=len(members),
                point_forecast_claimed=demand_class != "lumpy",
            )
        )
    return rows


def _demand_class_of(row: ForecastSeries) -> str:
    key = row.key if isinstance(row.key, dict) else {}
    value = key.get("demand_class")
    return str(value) if value else "unclassified"


def value_add(candidates: list[ModelCandidate]) -> ValueAdd | None:
    winner = next((c for c in candidates if c.selected), None)
    if winner is None:
        return None

    baselines = [
        c
        for c in candidates
        if c.model in BASELINE_MODELS and c is not winner and not c.failed and c.wmape is not None
    ]
    best = min(baselines, key=lambda c: c.wmape or float("inf")) if baselines else None

    return ValueAdd(
        model=winner.model.value,
        model_error=winner.wmape,
        baseline=best.model.value if best else None,
        baseline_error=best.wmape if best else None,
        improvement_pct=(
            forecast_value_add(winner.wmape, best.wmape)
            if best is not None and winner.wmape is not None and best.wmape is not None
            else None
        ),
    )


def coverage_rows(report: CoverageReport) -> list[dict[str, object]]:
    return report.as_dict()


def interval_coverage(points: list[ForecastPoint], nominal: float | None) -> CoverageReport:
    if nominal is None:
        return CoverageReport()

    banded = [
        (p.period, p.actual, p.lower_bound, p.upper_bound)
        for p in points
        if p.actual is not None and p.lower_bound is not None and p.upper_bound is not None
    ]
    if not banded:
        return CoverageReport()

    step_of = {period: step for step, period in enumerate(sorted({b[0] for b in banded}), 1)}
    return realised_coverage(
        (
            Interval(horizon=step_of[period], actual=actual, lower=lower, upper=upper)
            for period, actual, lower, upper in banded
        ),
        nominal,
    )


def _finite(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


@dataclass(slots=True)
class Headline:
    accuracy_pct: float | None
    runs_scored: int
    periods_scored: int
    measured_through: date | None

    @property
    def publishable(self) -> bool:
        return (
            self.accuracy_pct is not None
            and self.runs_scored >= MIN_RUNS_FOR_HEADLINE
            and self.periods_scored >= MIN_PERIODS_FOR_HEADLINE
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "accuracy_pct": _round(self.accuracy_pct),
            "runs_scored": self.runs_scored,
            "periods_scored": self.periods_scored,
            "measured_through": self.measured_through.isoformat()
            if self.measured_through
            else None,
            "publishable": self.publishable,
            "minimum_runs": MIN_RUNS_FOR_HEADLINE,
            "minimum_periods": MIN_PERIODS_FOR_HEADLINE,
        }


async def headline(session: AsyncSession) -> Headline:
    runs = list(
        (
            await session.execute(
                select(ForecastRun).where(
                    ForecastRun.scored_at.is_not(None),
                    ForecastRun.realized_wmape.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not runs:
        return Headline(None, 0, 0, None)

    weights = np.array([max(run.scored_periods, 0) for run in runs], dtype=float)
    errors = np.array([run.realized_wmape or 0.0 for run in runs], dtype=float)
    total = float(weights.sum())

    weighted = float((weights * errors).sum() / total) if total > 0 else float(errors.mean())
    through = max((run.scored_through for run in runs if run.scored_through), default=None)

    return Headline(
        accuracy_pct=max(0.0, 100.0 - weighted),
        runs_scored=len(runs),
        periods_scored=int(total),
        measured_through=through,
    )


async def build(session: AsyncSession, run_id: UUID) -> AccuracyReport | None:
    run = (
        await session.execute(select(ForecastRun).where(ForecastRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        return None

    points = list(
        (
            await session.execute(
                select(ForecastPoint).where(
                    ForecastPoint.run_id == run_id,
                    ForecastPoint.kind == PointKind.FORECAST,
                )
            )
        )
        .scalars()
        .all()
    )
    series = list(
        (await session.execute(select(ForecastSeries).where(ForecastSeries.run_id == run_id)))
        .scalars()
        .all()
    )
    candidates = list(
        (await session.execute(select(ModelCandidate).where(ModelCandidate.run_id == run_id)))
        .scalars()
        .all()
    )

    diagnostics = run.options if isinstance(run.options, dict) else {}
    measured = interval_coverage(points, run.confidence_level)
    report = AccuracyReport(
        run_id=run.id,
        dataset_id=run.dataset_id,
        as_of=run.scored_at,
        provenance=current_provenance(),
        backtest={
            "scheme": diagnostics.get("backtest_scheme", "expanding"),
            "origins": max((c.folds for c in candidates), default=0),
            "horizon": run.horizon,
            "validated_horizon": diagnostics.get("validated_horizon"),
            "confidence_level": run.confidence_level,
        },
        by_horizon=horizon_accuracy(points),
        by_class=class_accuracy(series),
        coverage=coverage_rows(measured),
        value_add=value_add(candidates),
    )

    if run.scored_at is None:
        report.caveats.append(
            "These figures come from held-out stretches of your own history. This run has not "
            "yet been scored against outcomes that arrived after it was issued."
        )
    if not report.by_horizon:
        report.caveats.append("No period of this run has finished yet, so nothing is scored.")

    validated = diagnostics.get("validated_horizon")
    if isinstance(validated, int) and validated < run.horizon:
        report.caveats.append(
            f"There was only enough history to validate {validated} step(s) ahead, so the "
            f"backtest figures do not cover the full {run.horizon} this run forecast. "
            "Error at the later steps is likely to be worse than shown."
        )

    report.caveats.extend(_coverage_caveats(measured, run.confidence_level))
    report.caveats.extend(_backtest_interval_caveats(diagnostics, run.confidence_level))

    return report


def _coverage_caveats(report: CoverageReport, nominal: float | None) -> list[str]:
    if nominal is None or not report.points:
        return []

    stated = f"{nominal * 100:.0f}%"
    if not report.measurable_points:
        seen = sum(point.n_observations for point in report.points)
        return [
            f"Too few finished periods ({seen}) to say whether the {stated} range is honest. "
            f"{MIN_COVERAGE_SAMPLE} per horizon are needed before the share means anything."
        ]

    if report.holds:
        return []

    gap = report.worst_gap_pp
    direction = "narrower" if gap < 0 else "wider"
    return [
        f"The {stated} range held {abs(gap):.0f} points off its promise at its worst horizon, "
        f"so it is {direction} than it claims. Treat the range as indicative, not as a bound."
    ]


def _backtest_interval_caveats(diagnostics: dict[str, object], nominal: float | None) -> list[str]:
    check = diagnostics.get("interval_check")
    if nominal is None or not isinstance(check, dict) or not check.get("measured"):
        return []

    # Per-horizon shares rest on a handful of origins each; the pooled one is
    # the figure with enough behind it to say out loud.
    if check.get("served_pooled_holds"):
        return []

    gap = check.get("served_pooled_gap_pp")
    if not isinstance(gap, int | float):
        return []

    direction = "narrower" if gap < 0 else "wider"
    seen = check.get("served_pooled_observations")
    evidence = f" over {seen} held-out period(s)" if isinstance(seen, int) and seen else ""
    return [
        f"On held-out stretches of your own history the {nominal * 100:.0f}% range came out "
        f"{abs(gap):.0f} points {direction} than it promises{evidence}."
    ]
