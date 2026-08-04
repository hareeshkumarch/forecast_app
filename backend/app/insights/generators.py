from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from app.database.base import utcnow
from app.models.enums import InsightSeverity, InsightType


@dataclass(slots=True)
class SegmentFact:
    label: str
    forecast_value: float
    change_vs_last_year: float | None
    share: float


@dataclass(slots=True)
class DriverFact:
    name: str
    impact_value: float
    impact_pct: float
    direction: str


@dataclass(slots=True)
class InsightContext:

    accuracy: float
    previous_accuracy: float | None
    wmape: float
    smape: float
    history: list[float]
    fitted: list[float | None]
    point_forecast: list[float]
    lower_bound: list[float]
    upper_bound: list[float]
    best_case: list[float]
    worst_case: list[float]
    confidence_level: float
    horizon: int
    frequency_label: str
    currency_like: bool
    regions: list[SegmentFact] = field(default_factory=list)
    categories: list[SegmentFact] = field(default_factory=list)
    drivers: list[DriverFact] = field(default_factory=list)
    model_label: str = "the selected model"


@dataclass(slots=True)
class GeneratedInsight:
    type: InsightType
    severity: InsightSeverity
    title: str
    explanation: str
    suggested_action: str
    metric_name: str
    metric_value: float
    metric_unit: str
    supporting_data: dict
    generated_at: datetime = field(default_factory=utcnow)

    weight: float = 0.0


def _fmt(value: float, currency_like: bool) -> str:
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    prefix = "$" if currency_like else ""

    if magnitude >= 1_000_000_000:
        return f"{sign}{prefix}{magnitude / 1_000_000_000:.2f}B"
    if magnitude >= 1_000_000:
        return f"{sign}{prefix}{magnitude / 1_000_000:.2f}M"
    if magnitude >= 1_000:
        return f"{sign}{prefix}{magnitude / 1_000:.1f}K"
    return f"{sign}{prefix}{magnitude:,.0f}"


def accuracy_change(ctx: InsightContext) -> GeneratedInsight | None:
    if not np.isfinite(ctx.accuracy):
        return None

    if ctx.previous_accuracy is None or not np.isfinite(ctx.previous_accuracy):

        if ctx.accuracy < 80:
            return GeneratedInsight(
                type=InsightType.ACCURACY_CHANGE,
                severity=InsightSeverity.WARNING,
                title="Forecast Accuracy Below Target",
                explanation=(
                    f"Backtested accuracy is {ctx.accuracy:.1f}% "
                    f"(wMAPE {ctx.wmape:.1f}%) using {ctx.model_label}. "
                    "Below 80%, period-level figures should be treated as directional."
                ),
                suggested_action=(
                    "Add more history or a cleaner target column, then re-run the forecast."
                ),
                metric_name="accuracy",
                metric_value=round(ctx.accuracy, 2),
                metric_unit="percent",
                supporting_data={"wmape": round(ctx.wmape, 3), "model": ctx.model_label},
                weight=70,
            )
        return GeneratedInsight(
            type=InsightType.ACCURACY_CHANGE,
            severity=InsightSeverity.POSITIVE,
            title="Strong Forecast Accuracy",
            explanation=(
                f"{ctx.model_label} achieved {ctx.accuracy:.1f}% accuracy in backtesting "
                f"(wMAPE {ctx.wmape:.1f}%), so period-level forecasts are reliable "
                "for planning."
            ),
            suggested_action="Use these figures directly in the operating plan.",
            metric_name="accuracy",
            metric_value=round(ctx.accuracy, 2),
            metric_unit="percent",
            supporting_data={"wmape": round(ctx.wmape, 3), "model": ctx.model_label},
            weight=60,
        )

    delta = ctx.accuracy - ctx.previous_accuracy
    if abs(delta) < 0.5:
        return None                   

    improving = delta > 0
    return GeneratedInsight(
        type=InsightType.ACCURACY_CHANGE,
        severity=InsightSeverity.POSITIVE if improving else InsightSeverity.WARNING,
        title="Accuracy Improving" if improving else "Accuracy Degrading",
        explanation=(
            f"Forecast accuracy {'rose' if improving else 'fell'} "
            f"{abs(delta):.1f} points to {ctx.accuracy:.1f}% versus the previous run "
            f"({ctx.previous_accuracy:.1f}%)."
        ),
        suggested_action=(
            "Keep the current model configuration."
            if improving
            else "Review recent data quality — a shift in the input often precedes this."
        ),
        metric_name="accuracy_delta",
        metric_value=round(delta, 2),
        metric_unit="percentage_points",
        supporting_data={
            "current": round(ctx.accuracy, 2),
            "previous": round(ctx.previous_accuracy, 2),
        },
        weight=75 if not improving else 65,
    )


def forecast_gap(ctx: InsightContext) -> GeneratedInsight | None:
    if not ctx.point_forecast or not ctx.history:
        return None

    window = min(len(ctx.point_forecast), len(ctx.history))
    if window == 0:
        return None

    baseline = float(np.sum(ctx.history[-window:]))
    projected = float(np.sum(ctx.point_forecast[:window]))
    if baseline == 0:
        return None

    change_pct = (projected - baseline) / abs(baseline) * 100.0
    if abs(change_pct) < 5.0:
        return None

    growing = change_pct > 0
    return GeneratedInsight(
        type=InsightType.FORECAST_GAP,
        severity=InsightSeverity.POSITIVE if growing else InsightSeverity.WARNING,
        title="High Growth Expected" if growing else "Contraction Expected",
        explanation=(
            f"The next {window} {ctx.frequency_label} are projected at "
            f"{_fmt(projected, ctx.currency_like)}, "
            f"{abs(change_pct):.1f}% {'above' if growing else 'below'} the trailing "
            f"{window} {ctx.frequency_label} ({_fmt(baseline, ctx.currency_like)})."
        ),
        suggested_action=(
            "Check that capacity and inventory plans are sized for the increase."
            if growing
            else "Revisit demand assumptions and pipeline coverage before committing the plan."
        ),
        metric_name="forecast_vs_trailing_pct",
        metric_value=round(change_pct, 2),
        metric_unit="percent",
        supporting_data={
            "forecast_total": round(projected, 2),
            "baseline_total": round(baseline, 2),
            "periods": window,
        },
        weight=80,
    )


def worst_case_risk(ctx: InsightContext) -> GeneratedInsight | None:
    if not ctx.point_forecast or not ctx.worst_case:
        return None

    base = float(np.sum(ctx.point_forecast))
    worst = float(np.sum(ctx.worst_case))
    if base == 0:
        return None

    downside_pct = (base - worst) / abs(base) * 100.0
    if downside_pct < 3.0:
        return None

    severe = downside_pct >= 15.0
    return GeneratedInsight(
        type=InsightType.WORST_CASE_RISK,
        severity=InsightSeverity.CRITICAL if severe else InsightSeverity.WARNING,
        title="Worst Case Scenario",
        explanation=(
            f"The worst case totals {_fmt(worst, ctx.currency_like)} over the horizon, "
            f"{downside_pct:.1f}% below the base case of {_fmt(base, ctx.currency_like)}. "
            f"That is a {_fmt(base - worst, ctx.currency_like)} shortfall at the "
            "95% scenario band."
        ),
        suggested_action=(
            "Build a contingency plan for the downside before committing to targets."
            if severe
            else "Hold a reserve sized to the gap between base and worst case."
        ),
        metric_name="worst_case_downside_pct",
        metric_value=round(downside_pct, 2),
        metric_unit="percent",
        supporting_data={
            "base_case_total": round(base, 2),
            "worst_case_total": round(worst, 2),
            "shortfall": round(base - worst, 2),
        },
        weight=85 if severe else 70,
    )


def confidence_widening(ctx: InsightContext) -> GeneratedInsight | None:
    if len(ctx.lower_bound) < 3 or len(ctx.upper_bound) < 3:
        return None

    widths = [high - low for high, low in zip(ctx.upper_bound, ctx.lower_bound, strict=False)]
    if not widths or widths[0] <= 0:
        return None

    growth = widths[-1] / widths[0]
    if growth < 1.8:
        return None

    first_pct = widths[0] / abs(ctx.point_forecast[0]) * 100 if ctx.point_forecast[0] else 0
    last_pct = widths[-1] / abs(ctx.point_forecast[-1]) * 100 if ctx.point_forecast[-1] else 0

    return GeneratedInsight(
        type=InsightType.CONFIDENCE_WIDENING,
        severity=InsightSeverity.INFO,
        title="Confidence Range Widens Sharply",
        explanation=(
            f"The {int(ctx.confidence_level * 100)}% interval grows "
            f"{growth:.1f}x across the horizon — from ±{first_pct / 2:.1f}% in the first "
            f"period to ±{last_pct / 2:.1f}% in the last."
        ),
        suggested_action=(
            "Treat the later periods as a planning range rather than a point number, "
            "and re-forecast as new actuals land."
        ),
        metric_name="interval_growth_ratio",
        metric_value=round(growth, 3),
        metric_unit="ratio",
        supporting_data={
            "first_period_width": round(widths[0], 2),
            "last_period_width": round(widths[-1], 2),
        },
        weight=45,
    )


def anomaly(ctx: InsightContext) -> GeneratedInsight | None:
    pairs = [
        (index, actual, fit)
        for index, (actual, fit) in enumerate(zip(ctx.history, ctx.fitted, strict=False))
        if fit is not None and np.isfinite(fit) and np.isfinite(actual)
    ]
    if len(pairs) < 8:
        return None

    residuals = np.array([actual - fit for _, actual, fit in pairs])
    sigma = float(np.std(residuals))
    if sigma == 0:
        return None


    tail = pairs[-6:]
    worst_index, worst_actual, worst_fit = max(
        tail, key=lambda item: abs(item[1] - item[2]) / sigma
    )
    z = (worst_actual - worst_fit) / sigma
    if abs(z) < 2.5:
        return None

    periods_ago = len(ctx.history) - 1 - worst_index
    above = z > 0
    return GeneratedInsight(
        type=InsightType.ANOMALY,
        severity=InsightSeverity.WARNING,
        title="Anomaly Detected",
        explanation=(
            f"{periods_ago} {ctx.frequency_label} ago, actuals came in at "
            f"{_fmt(worst_actual, ctx.currency_like)} against an expected "
            f"{_fmt(worst_fit, ctx.currency_like)} — {abs(z):.1f} standard deviations "
            f"{'above' if above else 'below'} the fitted trend."
        ),
        suggested_action=(
            "Confirm whether this was a one-off event. If it repeats, the model "
            "should be re-fitted with it treated as a regular pattern."
        ),
        metric_name="anomaly_z_score",
        metric_value=round(float(z), 2),
        metric_unit="std_dev",
        supporting_data={
            "actual": round(float(worst_actual), 2),
            "expected": round(float(worst_fit), 2),
            "periods_ago": periods_ago,
        },
        weight=78,
    )


def regional_growth(ctx: InsightContext) -> GeneratedInsight | None:
    ranked = [r for r in ctx.regions if r.change_vs_last_year is not None]
    if not ranked:
        return None

    top = max(ranked, key=lambda r: r.change_vs_last_year or 0.0)
    if (top.change_vs_last_year or 0.0) < 3.0:
        return None

    return GeneratedInsight(
        type=InsightType.REGIONAL_GROWTH,
        severity=InsightSeverity.POSITIVE,
        title="Top Growth Region",
        explanation=(
            f"{top.label} is growing fastest at {top.change_vs_last_year:.1f}% "
            f"year over year, with a forecast of {_fmt(top.forecast_value, ctx.currency_like)} "
            f"({top.share:.1f}% of the total)."
        ),
        suggested_action=f"Prioritise supply and headcount for {top.label} next cycle.",
        metric_name="region_growth_pct",
        metric_value=round(top.change_vs_last_year or 0.0, 2),
        metric_unit="percent",
        supporting_data={
            "region": top.label,
            "forecast_value": round(top.forecast_value, 2),
            "share_pct": round(top.share, 2),
        },
        weight=72,
    )


def category_decline(ctx: InsightContext) -> GeneratedInsight | None:
    ranked = [c for c in ctx.categories if c.change_vs_last_year is not None]
    if not ranked:
        return None

    worst = min(ranked, key=lambda c: c.change_vs_last_year or 0.0)
    if (worst.change_vs_last_year or 0.0) > -3.0:
        return None

    return GeneratedInsight(
        type=InsightType.CATEGORY_DECLINE,
        severity=InsightSeverity.WARNING,
        title="Category Decline",
        explanation=(
            f"{worst.label} is down {abs(worst.change_vs_last_year or 0):.1f}% year over year, "
            f"forecast at {_fmt(worst.forecast_value, ctx.currency_like)} "
            f"({worst.share:.1f}% of the total)."
        ),
        suggested_action=(
            f"Review pricing and promotion for {worst.label}, or reallocate the budget "
            "to growing categories."
        ),
        metric_name="category_change_pct",
        metric_value=round(worst.change_vs_last_year or 0.0, 2),
        metric_unit="percent",
        supporting_data={
            "category": worst.label,
            "forecast_value": round(worst.forecast_value, 2),
            "share_pct": round(worst.share, 2),
        },
        weight=74,
    )


def driver_positive(ctx: InsightContext) -> GeneratedInsight | None:
    positives = [d for d in ctx.drivers if d.impact_value > 0]
    if not positives:
        return None

    top = max(positives, key=lambda d: d.impact_value)
    if abs(top.impact_pct) < 5:
        return None

    return GeneratedInsight(
        type=InsightType.DRIVER_POSITIVE,
        severity=InsightSeverity.POSITIVE,
        title=f"Top Driver: {top.name}",
        explanation=(
            f"{top.name} contributes {_fmt(top.impact_value, ctx.currency_like)} to the "
            f"forecast, {abs(top.impact_pct):.1f}% of total movement — the largest "
            "positive driver."
        ),
        suggested_action=f"Protect the conditions behind {top.name.lower()} in the next plan.",
        metric_name="driver_impact",
        metric_value=round(top.impact_value, 2),
        metric_unit="absolute",
        supporting_data={"driver": top.name, "impact_pct": round(top.impact_pct, 2)},
        weight=68,
    )


def driver_negative(ctx: InsightContext) -> GeneratedInsight | None:
    negatives = [d for d in ctx.drivers if d.impact_value < 0]
    if not negatives:
        return None

    top = min(negatives, key=lambda d: d.impact_value)
    if abs(top.impact_pct) < 5:
        return None

    return GeneratedInsight(
        type=InsightType.DRIVER_NEGATIVE,
        severity=InsightSeverity.WARNING,
        title=f"Largest Drag: {top.name}",
        explanation=(
            f"{top.name} subtracts {_fmt(abs(top.impact_value), ctx.currency_like)} from the "
            f"forecast, {abs(top.impact_pct):.1f}% of total movement — the largest drag."
        ),
        suggested_action=f"Model a scenario with {top.name.lower()} held flat to size the upside.",
        metric_name="driver_impact",
        metric_value=round(top.impact_value, 2),
        metric_unit="absolute",
        supporting_data={"driver": top.name, "impact_pct": round(top.impact_pct, 2)},
        weight=76,
    )


def recommendation(ctx: InsightContext) -> GeneratedInsight | None:
    if not ctx.point_forecast:
        return None

    total = float(np.sum(ctx.point_forecast))
    top_region = max(ctx.regions, key=lambda r: r.forecast_value) if ctx.regions else None


    if np.isfinite(ctx.accuracy) and ctx.accuracy < 75:
        return GeneratedInsight(
            type=InsightType.RECOMMENDATION,
            severity=InsightSeverity.WARNING,
            title="Recommendation: Improve Input Data",
            explanation=(
                f"At {ctx.accuracy:.1f}% accuracy, this forecast is directional rather "
                "than plannable. More history, or a target column with fewer gaps, "
                "is the highest-leverage fix."
            ),
            suggested_action="Upload a longer history and re-run before setting targets.",
            metric_name="accuracy",
            metric_value=round(ctx.accuracy, 2),
            metric_unit="percent",
            supporting_data={"threshold": 75},
            weight=90,
        )

    worst_total = float(np.sum(ctx.worst_case)) if ctx.worst_case else total
    downside = (total - worst_total) / abs(total) * 100 if total else 0.0

    if downside >= 15:
        return GeneratedInsight(
            type=InsightType.RECOMMENDATION,
            severity=InsightSeverity.WARNING,
            title="Recommendation: Plan for the Downside",
            explanation=(
                f"The spread between base and worst case is "
                f"{_fmt(total - worst_total, ctx.currency_like)} ({downside:.1f}%). "
                "Committing to the base case alone leaves that gap unfunded."
            ),
            suggested_action=(
                f"Hold {_fmt((total - worst_total) * 0.5, ctx.currency_like)} in reserve, "
                "or stage commitments by period."
            ),
            metric_name="base_worst_spread_pct",
            metric_value=round(downside, 2),
            metric_unit="percent",
            supporting_data={"base_total": round(total, 2), "worst_total": round(worst_total, 2)},
            weight=88,
        )

    if top_region is not None:
        return GeneratedInsight(
            type=InsightType.RECOMMENDATION,
            severity=InsightSeverity.INFO,
            title="Recommendation: Concentrate Investment",
            explanation=(
                f"{top_region.label} accounts for {top_region.share:.1f}% of the forecast "
                f"({_fmt(top_region.forecast_value, ctx.currency_like)}). "
                "Incremental investment there compounds fastest."
            ),
            suggested_action=f"Weight the next budget cycle toward {top_region.label}.",
            metric_name="top_region_share_pct",
            metric_value=round(top_region.share, 2),
            metric_unit="percent",
            supporting_data={
                "region": top_region.label,
                "forecast_value": round(top_region.forecast_value, 2),
            },
            weight=55,
        )

    return GeneratedInsight(
        type=InsightType.RECOMMENDATION,
        severity=InsightSeverity.INFO,
        title="Recommendation: Hold Current Plan",
        explanation=(
            f"The forecast totals {_fmt(total, ctx.currency_like)} over the horizon with "
            f"{ctx.accuracy:.1f}% backtested accuracy and no material downside signal."
        ),
        suggested_action="Keep the current plan and re-forecast when new actuals land.",
        metric_name="forecast_total",
        metric_value=round(total, 2),
        metric_unit="absolute",
        supporting_data={"accuracy": round(ctx.accuracy, 2)},
        weight=40,
    )


GENERATORS: tuple[Callable[[InsightContext], GeneratedInsight | None], ...] = (
    accuracy_change,
    forecast_gap,
    worst_case_risk,
    anomaly,
    regional_growth,
    category_decline,
    driver_positive,
    driver_negative,
    confidence_widening,
    recommendation,
)
