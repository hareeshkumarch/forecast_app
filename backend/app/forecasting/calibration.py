"""Whether the intervals hold, and what to do when they do not.

"An honest range around every number" is printed on the homepage, and it is a
claim about coverage rather than about emitting quantiles. Emitting an 80%
interval costs nothing; the claim is that the actual lands inside it four times
in five. This module measures that against backtest folds, reports the gap when
it misses, and rescales the intervals off the held-out residuals so that it
stops missing.

Nothing here trusts the model's own variance estimate. A model that is
overconfident reports a small sigma and a narrow interval, and scoring its
intervals against its own sigma would agree with it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

#: How far the observed coverage may sit from the nominal level before the
#: homepage's claim is false. Five points on an 80% interval means anything
#: from 75% to 85% of actuals landing inside it.
COVERAGE_TOLERANCE_PP = 5.0

#: Below this many held-out points a coverage figure is noise. An 80% interval
#: measured on four observations can only read 0, 25, 50, 75 or 100.
MIN_COVERAGE_SAMPLE = 8


@dataclass(slots=True, frozen=True)
class CoveragePoint:
    nominal: float
    horizon: int
    observed: float
    n_observations: int

    @property
    def gap_pp(self) -> float:
        """Observed minus nominal, in percentage points. Negative is too narrow."""
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
        """True when every level this run can measure lands inside tolerance."""
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
    """One backtest observation, with the horizon it was forecast at."""

    horizon: int
    actual: float
    predicted: float


def measure_coverage(
    points: Iterable[HeldOutPoint],
    halfwidths: dict[int, float],
    nominal: float,
) -> CoverageReport:
    """Empirical coverage per horizon for one nominal level.

    `halfwidths` is what the served interval would have been at each horizon,
    so this measures the interval the customer would actually have seen.
    """
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


def conformal_halfwidths(
    points: Iterable[HeldOutPoint],
    nominal: float,
    *,
    enforce_monotone: bool = True,
) -> dict[int, float]:
    """Interval half-widths taken from held-out residuals, per horizon.

    Split conformal: the (1-alpha) empirical quantile of absolute residuals is
    the half-width that covers that share of them, with no distributional
    assumption. The rank used is ceil((n+1)(1-alpha))/n rather than the plain
    quantile — the finite-sample correction that makes the guarantee hold at
    small n instead of approximately.

    A horizon with too few residuals to place that rank inherits the widest
    half-width from the horizons before it, which is conservative in the
    direction that keeps the claim true.
    """
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
            # Not enough residuals to place the quantile: the largest one is
            # the most this sample can honestly support.
            halfwidths[horizon] = float(residuals[-1])
        else:
            halfwidths[horizon] = float(residuals[rank - 1])

    return widen_with_horizon(halfwidths) if enforce_monotone else halfwidths


def widen_with_horizon(halfwidths: dict[int, float]) -> dict[int, float]:
    """Force the intervals to be non-decreasing in horizon.

    Further out is less certain. A sample that says otherwise is saying it
    about a handful of residuals, not about the world, so the running maximum
    is carried forward rather than believed.
    """
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
    """Turn point forecasts into calibrated bounds."""
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
    """The calibration decided for one level, and the evidence for it."""

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
    """Measure what the model's own intervals covered, then fix them.

    `model_halfwidths` is what the model would have served unaided. Passing it
    is what makes the "before" figure meaningful — the gap between what was
    promised and what happened is the number that has to be visible internally
    before a customer sees the claim.
    """
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
    """What a normal-errors model would serve, for comparison against conformal."""
    from app.forecasting.backtest import normal_quantile

    z = normal_quantile(nominal)
    return {horizon: z * sigma for horizon, sigma in sigma_by_horizon.items()}
