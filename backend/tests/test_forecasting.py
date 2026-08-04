from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from app.forecasting.backtest import BacktestResult, FoldResult, plan_backtest
from app.forecasting.engine import (
    ForecastInput,
    InsufficientDataError,
    SegmentInput,
    SeriesInput,
    run_forecast,
)
from app.forecasting.features import build_design_matrix, build_feature_spec
from app.forecasting.frequency import add_periods, future_periods, infer_frequency
from app.forecasting.selection import COMPLEXITY_PENALTY, select_model
from app.models.enums import ForecastFrequency, ModelKind

MONTHLY = ForecastFrequency.MONTHLY


def make_series(n: int = 48, *, seed: int = 7) -> tuple[list[date], list[float]]:
    rng = np.random.default_rng(seed)
    periods = [add_periods(date(2022, 1, 1), i, MONTHLY) for i in range(n)]
    values = (
        100_000
        + 1_800 * np.arange(n)
        + 12_000 * np.sin(2 * np.pi * np.arange(n) / 12)
        + rng.normal(0, 3_500, n)
    )
    return periods, [float(v) for v in values]


def test_add_periods_clamps_month_end() -> None:
    assert add_periods(date(2024, 1, 31), 1, MONTHLY) == date(2024, 2, 29)
    assert add_periods(date(2023, 1, 31), 1, MONTHLY) == date(2023, 2, 28)


def test_add_periods_crosses_year_boundary() -> None:
    assert add_periods(date(2024, 11, 1), 3, MONTHLY) == date(2025, 2, 1)
    assert add_periods(date(2024, 10, 1), 2, ForecastFrequency.QUARTERLY) == date(2025, 4, 1)


def test_future_periods_are_contiguous() -> None:
    periods = future_periods(date(2025, 12, 1), 3, MONTHLY)
    assert periods == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]


def test_infer_frequency_from_spacing() -> None:
    monthly = [add_periods(date(2024, 1, 1), i, MONTHLY) for i in range(12)]
    assert infer_frequency(monthly) is MONTHLY

    daily = [add_periods(date(2024, 1, 1), i, ForecastFrequency.DAILY) for i in range(30)]
    assert infer_frequency(daily) is ForecastFrequency.DAILY


def test_infer_frequency_tolerates_gaps() -> None:
    periods = [add_periods(date(2024, 1, 1), i, MONTHLY) for i in range(12)]
    del periods[4]
    assert infer_frequency(periods) is MONTHLY


def test_features_never_leak_the_current_value() -> None:
    periods, values = make_series(60)
    array = np.asarray(values)
    spec = build_feature_spec(len(array), MONTHLY)

    matrix, target, names, rows = build_design_matrix(array, periods, spec, MONTHLY)


    for column_index, name in enumerate(names):
        if name.startswith(("lag_", "roll_")):
            assert not np.allclose(matrix[:, column_index], target), f"{name} leaks the target"


def test_feature_spec_leaves_trainable_rows() -> None:
    for n in (16, 20, 24, 30, 36, 42, 48, 60):
        periods = [add_periods(date(2020, 1, 1), i, MONTHLY) for i in range(n)]
        values = np.arange(n, dtype=float) + 100
        spec = build_feature_spec(n, MONTHLY)
        matrix, _, _, _ = build_design_matrix(values, periods, spec, MONTHLY)
        assert matrix.shape[0] >= 8, f"n={n} left only {matrix.shape[0]} training rows"


def test_backtest_folds_are_chronological_and_disjoint() -> None:
    plan = plan_backtest(48, 6, MONTHLY)

    assert plan.n_folds > 0
    assert plan.cut_points == sorted(plan.cut_points), "folds must move forward in time"

    for cut in plan.cut_points:
        assert cut + plan.horizon <= 48
        assert cut >= plan.initial_train


def test_backtest_horizon_is_capped_relative_to_history() -> None:
    plan = plan_backtest(30, 24, MONTHLY)
    assert plan.horizon <= 30 // 4


def test_backtest_returns_no_folds_for_tiny_history() -> None:
    assert plan_backtest(3, 6, MONTHLY).n_folds == 0


def _result(model: ModelKind, wmape: float, smape: float, rmse: float) -> BacktestResult:
    return BacktestResult(
        model=model,
        folds=[FoldResult(0, 10, 3, [1.0], [1.0])],
        mae=wmape,
        rmse=rmse,
        smape=smape,
        wmape=wmape,
    )


def test_selection_prefers_the_lowest_error() -> None:
    results = [
        _result(ModelKind.NAIVE, 15.0, 16.0, 2000.0),
        _result(ModelKind.HOLT_WINTERS, 5.0, 5.5, 900.0),
        _result(ModelKind.SARIMAX, 8.0, 8.5, 1200.0),
    ]
    selection = select_model(results)

    assert selection.winner is not None
    assert selection.winner.result.model is ModelKind.HOLT_WINTERS
    assert selection.winner.rank == 1


def test_complexity_penalty_breaks_near_ties_toward_simplicity() -> None:
    results = [
        _result(ModelKind.GRADIENT_BOOSTING, 10.0, 10.0, 1000.0),
        _result(ModelKind.NAIVE, 10.0, 10.0, 1000.0),
    ]
    selection = select_model(results)

    assert selection.winner is not None
    assert selection.winner.result.model is ModelKind.NAIVE


def test_complexity_penalty_cannot_override_real_accuracy() -> None:
    results = [
        _result(ModelKind.GRADIENT_BOOSTING, 4.0, 4.0, 500.0),
        _result(ModelKind.NAIVE, 12.0, 12.0, 1500.0),
    ]
    selection = select_model(results)

    assert selection.winner is not None
    assert selection.winner.result.model is ModelKind.GRADIENT_BOOSTING
    assert max(COMPLEXITY_PENALTY.values()) < 0.05


def test_failed_candidates_are_ranked_last_but_kept() -> None:
    good = _result(ModelKind.HOLT_WINTERS, 5.0, 5.0, 900.0)
    broken = BacktestResult(model=ModelKind.SARIMAX, failed=True, failure_reason="did not converge")

    selection = select_model([good, broken])

    assert selection.winner is not None
    assert selection.winner.result.model is ModelKind.HOLT_WINTERS

    models = {c.result.model for c in selection.candidates}
    assert ModelKind.SARIMAX in models


def test_selection_with_no_scoreable_candidate() -> None:
    broken = BacktestResult(model=ModelKind.SARIMAX, failed=True, failure_reason="nope")
    selection = select_model([broken])
    assert "No candidate" in selection.rationale


def test_full_run_produces_a_complete_result() -> None:
    periods, values = make_series(48)
    output = run_forecast(
        ForecastInput(
            series=SeriesInput(periods=periods, values=values),
            frequency=MONTHLY,
            horizon=6,
        )
    )

    assert len(output.point_forecast) == 6
    assert len(output.forecast_periods) == 6
    assert output.forecast_periods[0] == add_periods(periods[-1], 1, MONTHLY)
    assert all(math.isfinite(v) for v in output.point_forecast)
    assert output.selected_model in set(ModelKind)
    assert output.selection_rationale
    models = {row["model"] for row in output.candidates}
    assert models <= {kind.value for kind in ModelKind}
    assert {"naive", "seasonal_naive", "holt_winters", "theta", "sarimax", "gradient_boosting"} <= models


def test_bounds_bracket_the_point_forecast() -> None:
    periods, values = make_series(48)
    output = run_forecast(
        ForecastInput(series=SeriesInput(periods, values), frequency=MONTHLY, horizon=6)
    )

    for i, point in enumerate(output.point_forecast):
        assert output.lower_bound[i] <= point <= output.upper_bound[i]
        assert output.worst_case[i] <= point <= output.best_case[i]

        assert output.worst_case[i] <= output.lower_bound[i]
        assert output.best_case[i] >= output.upper_bound[i]


def test_intervals_widen_with_horizon() -> None:
    periods, values = make_series(48)
    output = run_forecast(
        ForecastInput(series=SeriesInput(periods, values), frequency=MONTHLY, horizon=6)
    )

    widths = [high - low for high, low in zip(output.upper_bound, output.lower_bound, strict=True)]
    assert widths[-1] >= widths[0], "uncertainty must not shrink with distance"


def test_run_is_deterministic() -> None:
    periods, values = make_series(48)
    payload = ForecastInput(series=SeriesInput(periods, values), frequency=MONTHLY, horizon=6)

    first = run_forecast(payload)
    second = run_forecast(payload)

    assert first.selected_model == second.selected_model
    assert first.point_forecast == second.point_forecast
    assert first.lower_bound == second.lower_bound


def test_short_history_falls_back_and_explains_why() -> None:
    periods, values = make_series(5)
    output = run_forecast(
        ForecastInput(series=SeriesInput(periods, values), frequency=MONTHLY, horizon=3)
    )

    assert output.used_fallback is True
    assert output.fallback_reason
    assert "history" in output.fallback_reason.lower()
    assert output.selected_model in (ModelKind.NAIVE, ModelKind.SEASONAL_NAIVE)
    assert len(output.point_forecast) == 3


def test_single_observation_raises() -> None:
    with pytest.raises(InsufficientDataError):
        run_forecast(
            ForecastInput(
                series=SeriesInput([date(2024, 1, 1)], [100.0]), frequency=MONTHLY, horizon=3
            )
        )


def test_segments_sum_to_the_total_forecast() -> None:
    periods, values = make_series(48)
    regions = [
        SegmentInput("North America", 480_000, 430_000, [1.0] * 12),
        SegmentInput("Europe", 290_000, 275_000, [1.0] * 12),
        SegmentInput("Asia Pacific", 210_000, 168_000, [1.0] * 12),
    ]

    output = run_forecast(
        ForecastInput(
            series=SeriesInput(periods, values),
            frequency=MONTHLY,
            horizon=6,
            regions=regions,
        )
    )

    total = sum(output.point_forecast)
    allocated = sum(segment.forecast_value for segment in output.regions)
    assert allocated == pytest.approx(total, rel=1e-6)


def test_segment_shares_sum_to_100() -> None:
    periods, values = make_series(48)
    output = run_forecast(
        ForecastInput(
            series=SeriesInput(periods, values),
            frequency=MONTHLY,
            horizon=6,
            categories=[
                SegmentInput("A", 400.0, 380.0, [1.0] * 12),
                SegmentInput("B", 300.0, 310.0, [1.0] * 12),
                SegmentInput("C", 300.0, 280.0, [1.0] * 12),
            ],
        )
    )

    assert sum(c.share for c in output.categories) == pytest.approx(100.0, abs=0.05)


def test_non_negative_target_keeps_bounds_non_negative() -> None:
    periods = [add_periods(date(2023, 1, 1), i, MONTHLY) for i in range(30)]
    values = [50.0] * 30

    output = run_forecast(
        ForecastInput(series=SeriesInput(periods, values), frequency=MONTHLY, horizon=6)
    )

    assert all(v >= 0 for v in output.lower_bound)
    assert all(v >= 0 for v in output.worst_case)


def test_drivers_are_produced_and_ranked() -> None:
    periods, values = make_series(48)
    output = run_forecast(
        ForecastInput(series=SeriesInput(periods, values), frequency=MONTHLY, horizon=6)
    )

    assert len(output.drivers) == 5
    impacts = [abs(d.impact_value) for d in output.drivers]
    assert impacts == sorted(impacts, reverse=True), "drivers must be ranked by impact"
