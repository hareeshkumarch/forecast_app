"""Which metrics a given series can actually be scored on.

A fixed set of error metrics reported for every series is a set that is wrong
for most of them. MAPE is undefined wherever an actual is zero and silently
scores the subset it can reach; RMSLE cannot see a negative; R² has nothing to
divide by when the target never moves; and on intermittent demand the point
metrics are measuring a number the router has already said is not meaningful.

So the metrics follow the data. `plan_for` reads the profile the diagnostics
already build — the same one that routes the models — and answers three
questions: which number to lead with, which may carry weight in a ranking,
and which are being withheld and for what reason. Nothing is dropped
silently: a metric that cannot be computed here is reported as withheld with
the reason, because "we did not show you MAPE" and "MAPE is undefined on a
third of your weeks" are very different messages.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from app.forecasting import metrics as m
from app.forecasting import routing
from app.forecasting.diagnostics import SeriesProfile

FloatArray = npt.NDArray[np.float64]

#: Scale-free, defined on every real value, and therefore askable of any
#: series at all. Everything else below has to earn its place.
UNIVERSAL: tuple[str, ...] = ("mae", "rmse", "medae", "bias", "wmape", "relative_bias")

#: Scaled against the series' own history, so they compare across products of
#: different volume. Unavailable only when there is no history to scale by.
SCALED: tuple[str, ...] = ("mase", "rmsse", "theil_u2")


@dataclass(slots=True, frozen=True)
class Withheld:
    name: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "reason": self.reason}


@dataclass(slots=True, frozen=True)
class MetricPlan:
    demand_class: str
    headline: str
    ranking: tuple[str, ...]
    reported: tuple[str, ...]
    withheld: tuple[Withheld, ...]
    seasonal_period: int
    point_forecast_is_meaningful: bool
    note: str

    def covers(self, name: str) -> bool:
        return name in self.reported

    def as_dict(self) -> dict[str, object]:
        return {
            "demand_class": self.demand_class,
            "headline": self.headline,
            "ranking": list(self.ranking),
            "reported": list(self.reported),
            "withheld": [item.as_dict() for item in self.withheld],
            "seasonal_period": self.seasonal_period,
            "point_forecast_is_meaningful": self.point_forecast_is_meaningful,
            "note": self.note,
        }


def plan_for(profile: SeriesProfile | None) -> MetricPlan:
    """Choose the metric set this series can be honestly scored on."""
    if profile is None:
        return MetricPlan(
            demand_class=routing.SMOOTH,
            headline="wmape",
            ranking=("wmape", "mae", "rmse"),
            reported=UNIVERSAL,
            withheld=(
                Withheld("mase", "No profile for this series, so there is no scale to divide by."),
                Withheld("rmsse", "No profile for this series, so there is no scale to divide by."),
            ),
            seasonal_period=1,
            point_forecast_is_meaningful=True,
            note="Scored on the metrics that need nothing but the numbers themselves.",
        )

    reported = list(UNIVERSAL)
    withheld: list[Withheld] = []
    demand_class = profile.demand_class
    # Bursty demand is a statement about a series that counts things. A signed
    # series has no periods "with no demand" in it — every reading either side
    # of zero is an observation — so its interval and CV² are describing
    # something the Syntetos-Boylan grid was not drawn for, and leading with
    # "demand arrives in bursts" would be telling the reader a fact about
    # their data that is not true of it.
    intermittent = profile.non_negative and demand_class in {
        routing.INTERMITTENT,
        routing.LUMPY,
        routing.NO_DEMAND,
    }

    lag = profile.seasonal_period if profile.has_seasonality else 1

    if profile.n_observations > lag:
        reported.extend(SCALED)
    else:
        for name in SCALED:
            withheld.append(
                Withheld(
                    name,
                    f"Needs more than {lag} period(s) of history to build a scale; this series has "
                    f"{profile.n_observations}.",
                )
            )

    zero_share = profile.zero_share
    if zero_share > 0:
        share = f"{zero_share:.0%}"
        withheld.append(
            Withheld("mape", f"Undefined where the actual is zero, and {share} of periods are.")
        )
        withheld.append(
            Withheld(
                "smape",
                f"Scores only the periods that are not zero, and {share} of these are — the number "
                "would describe a different sample from every other metric here.",
            )
        )
    else:
        reported.append("mape")
        reported.append("smape")

    # Non-negative, not strictly positive: `log1p` is defined at zero, so a
    # series that legitimately sells nothing some weeks can still be scored in
    # log space. Only an actual negative breaks it.
    if profile.non_negative:
        reported.append("rmsle")
    else:
        withheld.append(
            Withheld("rmsle", "Defined on non-negative values only; this series goes below zero.")
        )

    if profile.coefficient_of_variation > 0:
        reported.append("r_squared")
    else:
        withheld.append(
            Withheld("r_squared", "The target never moves, so it has no variance to account for.")
        )

    reported.append("residual_acf1")

    if intermittent:
        headline = "rmsse" if "rmsse" in reported else "mae"
        ranking = tuple(name for name in ("rmsse", "mase", "mae") if name in reported)
        note = (
            f"Demand arrives in bursts ({demand_class}), so the scale-free metrics lead and the "
            "percentage ones are withheld rather than shown against a handful of non-zero weeks."
        )
    elif profile.has_seasonality:
        headline = "mase" if "mase" in reported else "wmape"
        ranking = tuple(name for name in ("mase", "wmape", "rmse") if name in reported)
        note = (
            f"Seasonal at a period of {profile.seasonal_period}, so the scale is the seasonal step "
            "rather than the week-to-week one."
        )
    else:
        headline = "wmape"
        ranking = tuple(name for name in ("wmape", "mase", "rmse") if name in reported)
        note = "Steady demand, so volume-weighted error is the number to lead with."

    return MetricPlan(
        demand_class=demand_class,
        headline=headline,
        ranking=ranking,
        reported=tuple(dict.fromkeys(reported)),
        withheld=tuple(withheld),
        seasonal_period=lag,
        point_forecast_is_meaningful=routing.route(profile).point_forecast_is_meaningful,
        note=note,
    )


def evaluate_plan(
    plan: MetricPlan,
    y_true: FloatArray,
    y_pred: FloatArray,
    *,
    insample: FloatArray | None = None,
    weights: FloatArray | None = None,
) -> dict[str, float]:
    """Compute exactly the metrics the plan says this series can carry.

    The withheld ones are not computed and then hidden — they are not
    computed. A number that is undefined for the data has no value worth
    keeping around for something downstream to pick up by mistake.
    """
    history = (
        np.asarray(insample, dtype=float).ravel()
        if insample is not None
        else np.asarray([], dtype=float)
    )
    lag = plan.seasonal_period

    computed: dict[str, float] = {}
    for name in plan.reported:
        if name == "mae":
            computed[name] = m.mae(y_true, y_pred)
        elif name == "rmse":
            computed[name] = m.rmse(y_true, y_pred)
        elif name == "medae":
            computed[name] = m.medae(y_true, y_pred)
        elif name == "bias":
            computed[name] = m.bias(y_true, y_pred)
        elif name == "relative_bias":
            computed[name] = m.relative_bias(y_true, y_pred)
        elif name == "wmape":
            computed[name] = m.wmape(y_true, y_pred, weights)
        elif name == "mape":
            computed[name] = m.mape(y_true, y_pred)
        elif name == "smape":
            computed[name] = m.smape(y_true, y_pred)
        elif name == "rmsle":
            computed[name] = m.rmsle(y_true, y_pred)
        elif name == "r_squared":
            computed[name] = m.r_squared(y_true, y_pred)
        elif name == "residual_acf1":
            computed[name] = m.residual_acf1(y_true, y_pred)
        elif name == "mase":
            computed[name] = m.mase(y_true, y_pred, history, lag)
        elif name == "rmsse":
            computed[name] = m.rmsse(y_true, y_pred, history, lag)
        elif name == "theil_u2":
            computed[name] = m.theil_u2(y_true, y_pred, history, lag)

    return computed
