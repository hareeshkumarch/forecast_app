from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

COVERAGE_TOLERANCE_PP = 5.0

MIN_COVERAGE_SAMPLE = 8


@dataclass(slots=True, frozen=True)
class CoveragePoint:
    nominal: float
    horizon: int
    observed: float
    n_observations: int

    @property
    def gap_pp(self) -> float:
        return (self.observed - self.nominal) * 100.0

    @property
    def measurable(self) -> bool:
        return self.n_observations >= MIN_COVERAGE_SAMPLE

    @property
    def holds(self) -> bool:
        return abs(self.gap_pp) <= COVERAGE_TOLERANCE_PP


@dataclass(slots=True)
class CoverageReport:
    points: list[CoveragePoint] = field(default_factory=list)

    @property
    def measurable_points(self) -> list[CoveragePoint]:
        return [point for point in self.points if point.measurable]

    @property
    def worst_gap_pp(self) -> float:
        measurable = self.measurable_points
        if not measurable:
            return float("nan")
        return max(measurable, key=lambda point: abs(point.gap_pp)).gap_pp

    @property
    def holds(self) -> bool:
        measurable = self.measurable_points
        return bool(measurable) and all(point.holds for point in measurable)

    def by_level(self, nominal: float) -> list[CoveragePoint]:
        return sorted(
            (point for point in self.points if point.nominal == nominal),
            key=lambda point: point.horizon,
        )

    def as_dict(self) -> list[dict[str, object]]:
        return [
            {
                "nominal": round(point.nominal, 4),
                "horizon": point.horizon,
                "observed": round(point.observed, 4),
                "gap_pp": round(point.gap_pp, 2),
                "n_observations": point.n_observations,
                "measurable": point.measurable,
                "holds": point.holds,
            }
            for point in self.points
        ]


@dataclass(slots=True, frozen=True)
class HeldOutPoint:
    horizon: int
    actual: float
    predicted: float


def measure_coverage(
    points: Iterable[HeldOutPoint],
    halfwidths: dict[int, float],
    nominal: float,
) -> CoverageReport:
    grouped: dict[int, list[HeldOutPoint]] = {}
    for point in points:
        grouped.setdefault(point.horizon, []).append(point)

    report = CoverageReport()
    for horizon in sorted(grouped):
        halfwidth = halfwidths.get(horizon)
        if halfwidth is None or not np.isfinite(halfwidth):
            continue
        members = grouped[horizon]
        inside = sum(
            1 for point in members if abs(point.actual - point.predicted) <= halfwidth + 1e-9
        )
        report.points.append(
            CoveragePoint(
                nominal=nominal,
                horizon=horizon,
                observed=inside / len(members),
                n_observations=len(members),
            )
        )
    return report


@dataclass(slots=True, frozen=True)
class Interval:
    horizon: int
    actual: float
    lower: float
    upper: float

    @property
    def usable(self) -> bool:
        return bool(np.isfinite([self.actual, self.lower, self.upper]).all())

    @property
    def contains(self) -> bool:
        return self.lower - 1e-9 <= self.actual <= self.upper + 1e-9


def realised_coverage(intervals: Iterable[Interval], nominal: float) -> CoverageReport:
    grouped: dict[int, list[Interval]] = {}
    for interval in intervals:
        if interval.usable:
            grouped.setdefault(interval.horizon, []).append(interval)

    report = CoverageReport()
    for horizon in sorted(grouped):
        members = grouped[horizon]
        report.points.append(
            CoveragePoint(
                nominal=nominal,
                horizon=horizon,
                observed=sum(1 for member in members if member.contains) / len(members),
                n_observations=len(members),
            )
        )
    return report


def conformal_halfwidths(
    points: Iterable[HeldOutPoint],
    nominal: float,
    *,
    enforce_monotone: bool = True,
) -> dict[int, float]:
    level = min(max(float(nominal), 0.0), 1.0)

    grouped: dict[int, list[float]] = {}
    for point in points:
        residual = abs(point.actual - point.predicted)
        if np.isfinite(residual):
            grouped.setdefault(point.horizon, []).append(residual)

    halfwidths: dict[int, float] = {}
    for horizon in sorted(grouped):
        residuals = np.sort(np.asarray(grouped[horizon], dtype=float))
        n = residuals.size
        if n == 0:
            continue
        rank = int(np.ceil((n + 1) * level))
        if rank > n:
            halfwidths[horizon] = float(residuals[-1])
        else:
            halfwidths[horizon] = float(residuals[rank - 1])

    return widen_with_horizon(halfwidths) if enforce_monotone else halfwidths


def widen_with_horizon(halfwidths: dict[int, float]) -> dict[int, float]:
    widened: dict[int, float] = {}
    running = float("-inf")
    for horizon in sorted(halfwidths):
        running = max(running, halfwidths[horizon])
        widened[horizon] = running
    return widened


def is_monotone_in_horizon(halfwidths: dict[int, float]) -> bool:
    values = [halfwidths[horizon] for horizon in sorted(halfwidths)]
    return all(later >= earlier - 1e-9 for earlier, later in pairwise(values))


def apply_halfwidths(
    predictions: Sequence[float],
    horizons: Sequence[int],
    halfwidths: dict[int, float],
) -> tuple[list[float], list[float]]:
    if len(predictions) != len(horizons):
        raise ValueError("predictions and horizons must be the same length")

    lower: list[float] = []
    upper: list[float] = []
    widest = max(halfwidths.values(), default=float("nan"))
    for prediction, horizon in zip(predictions, horizons, strict=True):
        halfwidth = halfwidths.get(horizon, widest)
        if not np.isfinite(halfwidth):
            lower.append(float("nan"))
            upper.append(float("nan"))
            continue
        lower.append(float(prediction - halfwidth))
        upper.append(float(prediction + halfwidth))
    return lower, upper


@dataclass(slots=True)
class Calibration:
    nominal: float
    halfwidths: dict[int, float]
    before: CoverageReport
    after: CoverageReport

    @property
    def improved(self) -> bool:
        before = self.before.worst_gap_pp
        after = self.after.worst_gap_pp
        if not np.isfinite(before):
            return np.isfinite(after)
        if not np.isfinite(after):
            return False
        return abs(after) <= abs(before) + 1e-9

    def as_dict(self) -> dict[str, object]:
        return {
            "nominal": round(self.nominal, 4),
            "halfwidths": {str(h): round(w, 6) for h, w in sorted(self.halfwidths.items())},
            "coverage_before": self.before.as_dict(),
            "coverage_after": self.after.as_dict(),
            "worst_gap_before_pp": _round_or_none(self.before.worst_gap_pp),
            "worst_gap_after_pp": _round_or_none(self.after.worst_gap_pp),
            "holds": self.after.holds,
        }


def calibrate(
    points: Sequence[HeldOutPoint],
    nominal: float,
    model_halfwidths: dict[int, float] | None = None,
) -> Calibration:
    conformal = conformal_halfwidths(points, nominal)
    before = (
        measure_coverage(points, model_halfwidths, nominal)
        if model_halfwidths
        else CoverageReport()
    )
    after = measure_coverage(points, conformal, nominal)
    return Calibration(nominal=nominal, halfwidths=conformal, before=before, after=after)


def _round_or_none(value: float) -> float | None:
    return None if not np.isfinite(value) else round(value, 2)


def gaussian_halfwidths(
    sigma_by_horizon: dict[int, float],
    nominal: float,
) -> dict[int, float]:
    from app.forecasting.backtest import normal_quantile

    z = normal_quantile(nominal)
    return {horizon: z * sigma for horizon, sigma in sigma_by_horizon.items()}
