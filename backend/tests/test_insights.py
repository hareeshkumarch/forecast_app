from __future__ import annotations

import numpy as np

from app.insights.engine import generate_insights
from app.insights.generators import (
    DriverFact,
    InsightContext,
    SegmentFact,
    accuracy_change,
    anomaly,
    category_decline,
    forecast_gap,
    worst_case_risk,
)
from app.insights.llm import _numbers_preserved
from app.models.enums import InsightSeverity, InsightType


def make_context(**overrides: object) -> InsightContext:
    history = [100.0 + i for i in range(24)]
    base = {
        "accuracy": 92.0,
        "previous_accuracy": None,
        "wmape": 8.0,
        "smape": 8.4,
        "history": history,
        "fitted": [None, *[100.0 + i for i in range(23)]],
        "point_forecast": [130.0] * 6,
        "lower_bound": [120.0] * 6,
        "upper_bound": [140.0] * 6,
        "best_case": [150.0] * 6,
        "worst_case": [110.0] * 6,
        "confidence_level": 0.8,
        "horizon": 6,
        "frequency_label": "months",
        "currency_like": True,
        "regions": [],
        "categories": [],
        "drivers": [],
        "model_label": "Holt Winters",
    }
    base.update(overrides)
    return InsightContext(**base)  # type: ignore[arg-type]


def test_strong_accuracy_is_reported_positively() -> None:
    insight = accuracy_change(make_context(accuracy=94.0))

    assert insight is not None
    assert insight.severity is InsightSeverity.POSITIVE
    assert insight.metric_value == 94.0


def test_low_accuracy_warns() -> None:
    insight = accuracy_change(make_context(accuracy=68.0))

    assert insight is not None
    assert insight.severity is InsightSeverity.WARNING
    assert "below" in insight.title.lower() or "below" in insight.explanation.lower()


def test_accuracy_noise_is_suppressed() -> None:
    assert accuracy_change(make_context(accuracy=92.0, previous_accuracy=91.95)) is None


def test_accuracy_degradation_is_flagged() -> None:
    insight = accuracy_change(make_context(accuracy=85.0, previous_accuracy=93.0))

    assert insight is not None
    assert insight.severity is InsightSeverity.WARNING
    assert insight.metric_value < 0


def test_forecast_gap_detects_growth() -> None:

    insight = forecast_gap(make_context(point_forecast=[200.0] * 6))

    assert insight is not None
    assert insight.type is InsightType.FORECAST_GAP
    assert insight.metric_value > 0


def test_forecast_gap_ignores_small_moves() -> None:
    history = [100.0] * 24
    assert forecast_gap(make_context(history=history, point_forecast=[102.0] * 6)) is None


def test_worst_case_risk_escalates_when_severe() -> None:
    insight = worst_case_risk(make_context(point_forecast=[100.0] * 6, worst_case=[70.0] * 6))

    assert insight is not None
    assert insight.severity is InsightSeverity.CRITICAL
    assert insight.metric_value == 30.0


def test_worst_case_risk_is_silent_when_downside_is_small() -> None:
    assert worst_case_risk(make_context(point_forecast=[100.0] * 6, worst_case=[99.0] * 6)) is None


def test_anomaly_detects_a_real_outlier() -> None:
    history = [100.0] * 20
    fitted = [100.0] * 20
    history[-2] = 400.0                                     

    insight = anomaly(make_context(history=history, fitted=fitted))

    assert insight is not None
    assert insight.type is InsightType.ANOMALY
    assert abs(insight.metric_value) >= 2.5


def test_anomaly_is_silent_on_a_clean_series() -> None:
    history = [100.0 + (i % 3) for i in range(24)]
    assert anomaly(make_context(history=history, fitted=history)) is None


def test_category_decline_picks_the_worst_category() -> None:
    insight = category_decline(
        make_context(
            categories=[
                SegmentFact("Product A", 400.0, 12.0, 40.0),
                SegmentFact("Product C", 200.0, -18.0, 20.0),
            ]
        )
    )

    assert insight is not None
    assert "Product C" in insight.explanation
    assert insight.metric_value == -18.0


def test_category_decline_silent_when_all_growing() -> None:
    assert (
        category_decline(
            make_context(categories=[SegmentFact("A", 400.0, 10.0, 100.0)])
        )
        is None
    )


def test_engine_ranks_critical_above_informational() -> None:
    insights = generate_insights(
        make_context(
            point_forecast=[100.0] * 6,
            worst_case=[60.0] * 6,
            regions=[SegmentFact("APAC", 500.0, 25.0, 50.0)],
        )
    )

    assert len(insights) > 1
    severities = [i.severity for i in insights]
    assert severities[0] in (InsightSeverity.CRITICAL, InsightSeverity.WARNING)


def test_every_insight_carries_a_finite_metric() -> None:
    insights = generate_insights(make_context())

    assert len(insights) > 0
    for insight in insights:
        assert np.isfinite(insight.metric_value)
        assert insight.metric_name
        assert insight.title
        assert insight.explanation
        assert insight.suggested_action
        assert insight.generated_at is not None


def test_engine_respects_the_limit() -> None:
    context = make_context(
        point_forecast=[200.0] * 6,
        worst_case=[100.0] * 6,
        regions=[SegmentFact("APAC", 500.0, 25.0, 50.0)],
        categories=[SegmentFact("C", 100.0, -20.0, 10.0)],
        drivers=[DriverFact("Volume Growth", 500.0, 40.0, "up")],
    )
    assert len(generate_insights(context, limit=3)) == 3


def test_a_broken_generator_does_not_blank_the_rail(monkeypatch) -> None:
    import app.insights.engine as engine_module

    def exploding(_: InsightContext):  # noqa: ANN202
        raise RuntimeError("boom")

    monkeypatch.setattr(
        engine_module, "GENERATORS", (exploding, worst_case_risk, accuracy_change)
    )

    insights = engine_module.generate_insights(
        make_context(point_forecast=[100.0] * 6, worst_case=[70.0] * 6)
    )
    assert len(insights) >= 1


def test_llm_rewrite_must_not_invent_numbers() -> None:
    original = "Revenue grows 12.4% to $2.48M over 6 months."

    assert _numbers_preserved(original, "Revenue climbs 12.4% reaching $2.48M across 6 months.")

    assert not _numbers_preserved(original, "Revenue climbs 18.9% reaching $3.10M.")


def test_llm_rewrite_may_drop_a_figure() -> None:
    original = "Revenue grows 12.4% to $2.48M over 6 months."
    assert _numbers_preserved(original, "Revenue grows to $2.48M.")
