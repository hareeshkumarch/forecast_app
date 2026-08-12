"""Which models a series is allowed to be forecast with.

The Syntetos-Boylan quadrant, applied as a gate rather than as a hint. A
spreadsheet from a real business contains intermittent series — a part that
sells eleven times a year, a size that moves in one region only — and a
smooth-demand model fitted to one of those produces a confident number with no
support under it. Exponential smoothing on demand that is zero four weeks in
five will happily report 0.7 units a week and a tight interval around it.

Adding Croston to the roster is not enough on its own: if the smooth models
stay in the roster beside it, the selector can still pick one of them on a
fold where the zeros happened to line up. The classification has to remove
them.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.forecasting.diagnostics import (
    SYNTETOS_BOYLAN_ADI,
    SYNTETOS_BOYLAN_CV2,
    SeriesProfile,
)
from app.models.enums import ModelKind

#: Baselines. These run for every series whatever its class — they are the
#: floor the chosen model has to beat, and they are defined on any history.
BASELINE_MODELS: frozenset[ModelKind] = frozenset(
    {
        ModelKind.NAIVE,
        ModelKind.SEASONAL_NAIVE,
    }
)

#: Models that assume demand arrives every period. On intermittent demand they
#: fit the zeros as though they were observations of a level.
SMOOTH_DEMAND_MODELS: frozenset[ModelKind] = frozenset(
    {
        ModelKind.HOLT_WINTERS,
        ModelKind.ETS,
        ModelKind.THETA,
        ModelKind.SARIMAX,
        ModelKind.PROPHET,
        ModelKind.GRADIENT_BOOSTING,
    }
)

#: Models built for demand that arrives in gaps.
INTERMITTENT_MODELS: frozenset[ModelKind] = frozenset({ModelKind.CROSTON})

SMOOTH = "smooth"
ERRATIC = "erratic"
INTERMITTENT = "intermittent"
LUMPY = "lumpy"
NO_DEMAND = "no_demand"


@dataclass(slots=True, frozen=True)
class Routing:
    demand_class: str
    allowed: frozenset[ModelKind]
    #: Whether a single number is a defensible thing to show for this series.
    point_forecast_is_meaningful: bool
    #: Whether the intervals should be widened beyond what the fold residuals
    #: alone suggest.
    widen_intervals: bool
    reason: str

    def permits(self, kind: ModelKind) -> bool:
        return kind in self.allowed

    def as_dict(self) -> dict[str, object]:
        return {
            "demand_class": self.demand_class,
            "allowed_models": sorted(kind.value for kind in self.allowed),
            "point_forecast_is_meaningful": self.point_forecast_is_meaningful,
            "widen_intervals": self.widen_intervals,
            "reason": self.reason,
        }


def classify(demand_interval: float, demand_cv2: float) -> str:
    """The SBC quadrant for an average inter-demand interval and a size CV squared."""
    if demand_interval != demand_interval or demand_interval == float("inf"):
        return NO_DEMAND
    lumpy_interval = demand_interval >= SYNTETOS_BOYLAN_ADI
    variable_size = demand_cv2 >= SYNTETOS_BOYLAN_CV2
    if lumpy_interval and variable_size:
        return LUMPY
    if lumpy_interval:
        return INTERMITTENT
    if variable_size:
        return ERRATIC
    return SMOOTH


def route(profile: SeriesProfile | None) -> Routing:
    """The models this series may be forecast with, and what may be claimed."""
    if profile is None:
        return Routing(
            demand_class=SMOOTH,
            allowed=BASELINE_MODELS | SMOOTH_DEMAND_MODELS | INTERMITTENT_MODELS,
            point_forecast_is_meaningful=True,
            widen_intervals=False,
            reason="No profile was supplied, so every candidate is offered.",
        )

    demand_class = profile.demand_class

    if demand_class == LUMPY:
        return Routing(
            demand_class=LUMPY,
            allowed=BASELINE_MODELS | INTERMITTENT_MODELS,
            point_forecast_is_meaningful=False,
            widen_intervals=True,
            reason=(
                f"Demand arrives about every {profile.demand_interval:.1f} periods and the "
                f"size varies widely when it does (CV squared {profile.demand_cv2:.2f}). "
                "A single number would imply a regularity this series does not have, so "
                "quantiles are reported and the point forecast is not claimed."
            ),
        )

    if demand_class == INTERMITTENT:
        return Routing(
            demand_class=INTERMITTENT,
            allowed=BASELINE_MODELS | INTERMITTENT_MODELS,
            point_forecast_is_meaningful=True,
            widen_intervals=True,
            reason=(
                f"Demand arrives about every {profile.demand_interval:.1f} periods. "
                "Smooth-demand models fit the empty periods as observations of a level, "
                "so they are not offered for this series."
            ),
        )

    if demand_class == NO_DEMAND:
        return Routing(
            demand_class=NO_DEMAND,
            allowed=BASELINE_MODELS,
            point_forecast_is_meaningful=False,
            widen_intervals=True,
            reason="This series has fewer than two periods with any demand in them.",
        )

    if demand_class == ERRATIC:
        return Routing(
            demand_class=ERRATIC,
            allowed=BASELINE_MODELS | SMOOTH_DEMAND_MODELS,
            point_forecast_is_meaningful=True,
            widen_intervals=True,
            reason=(
                f"Demand arrives regularly but its size varies widely "
                f"(CV squared {profile.demand_cv2:.2f}), so the intervals are widened."
            ),
        )

    return Routing(
        demand_class=SMOOTH,
        allowed=BASELINE_MODELS | SMOOTH_DEMAND_MODELS,
        point_forecast_is_meaningful=True,
        widen_intervals=False,
        reason="Demand arrives regularly and at a consistent size.",
    )
