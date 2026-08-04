from __future__ import annotations

import numpy as np

from app.core.logging import get_logger
from app.forecasting.engine import ForecastOutput
from app.insights.generators import (
    GENERATORS,
    DriverFact,
    GeneratedInsight,
    InsightContext,
    SegmentFact,
)
from app.models.enums import ForecastFrequency, InsightSeverity

logger = get_logger(__name__)

FREQUENCY_LABEL: dict[ForecastFrequency, str] = {
    ForecastFrequency.DAILY: "days",
    ForecastFrequency.WEEKLY: "weeks",
    ForecastFrequency.MONTHLY: "months",
    ForecastFrequency.QUARTERLY: "quarters",
}


SEVERITY_BONUS: dict[InsightSeverity, float] = {
    InsightSeverity.CRITICAL: 30.0,
    InsightSeverity.WARNING: 15.0,
    InsightSeverity.POSITIVE: 5.0,
    InsightSeverity.INFO: 0.0,
}


def build_context(
    output: ForecastOutput,
    *,
    frequency: ForecastFrequency,
    confidence_level: float,
    previous_accuracy: float | None,
    currency_like: bool,
) -> InsightContext:
    return InsightContext(
        accuracy=output.metrics.get("accuracy", float("nan")),
        previous_accuracy=previous_accuracy,
        wmape=output.metrics.get("wmape", float("nan")),
        smape=output.metrics.get("smape", float("nan")),
        history=output.history_values,
        fitted=output.fitted_values,
        point_forecast=output.point_forecast,
        lower_bound=output.lower_bound,
        upper_bound=output.upper_bound,
        best_case=output.best_case,
        worst_case=output.worst_case,
        confidence_level=confidence_level,
        horizon=len(output.point_forecast),
        frequency_label=FREQUENCY_LABEL[frequency],
        currency_like=currency_like,
        regions=[
            SegmentFact(
                label=r.label,
                forecast_value=r.forecast_value,
                change_vs_last_year=r.change_vs_last_year,
                share=r.share,
            )
            for r in output.regions
        ],
        categories=[
            SegmentFact(
                label=c.label,
                forecast_value=c.forecast_value,
                change_vs_last_year=c.change_vs_last_year,
                share=c.share,
            )
            for c in output.categories
        ],
        drivers=[
            DriverFact(
                name=d.name,
                impact_value=d.impact_value,
                impact_pct=d.impact_pct,
                direction=d.direction,
            )
            for d in output.drivers
        ],
        model_label=output.selected_model.value.replace("_", " ").title(),
    )


def generate_insights(context: InsightContext, *, limit: int = 8) -> list[GeneratedInsight]:
    produced: list[GeneratedInsight] = []

    for generator in GENERATORS:
        try:
            insight = generator(context)
        except Exception:
            logger.exception("Insight generator %s failed", generator.__name__)
            continue

        if insight is None:
            continue


        if not np.isfinite(insight.metric_value):
            logger.debug("Skipping %s: non-finite metric", generator.__name__)
            continue

        produced.append(insight)

    produced.sort(key=lambda i: i.weight + SEVERITY_BONUS[i.severity], reverse=True)
    return produced[:limit]
