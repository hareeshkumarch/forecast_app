from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.forecasting.backtest import (
    BacktestResult,
    FoldResult,
    plan_backtest,
    run_backtest,
)
from app.forecasting.engine import _held_out
from app.forecasting.hierarchy import all_non_negative, reconcile_to_total
from app.forecasting.metrics import mase
from app.forecasting.models import Forecaster
from app.forecasting.scenarios import _residuals_by_step
from app.models.enums import ForecastFrequency, ModelKind

DAILY = ForecastFrequency.DAILY


class Flat(Forecaster):
    min_observations = 2

    def __init__(self) -> None:
        self.level = 0.0

    @property
    def params(self) -> dict[str, object]:
        return {}

    def fit(self, y: np.ndarray, periods: list[date]) -> None:
        self.level = float(np.nanmean(y))

    def predict(self, horizon: int, periods: list[date]) -> np.ndarray:
        return np.full(horizon, self.level)


class Zero(Flat):
    # Predicts zero whatever it was fitted on, so a residual names its horizon.
    def predict(self, horizon: int, periods: list[date]) -> np.ndarray:
        return np.zeros(horizon)


STEP_MARK = 1000.0


def _gapped_run(gap_step: int | None) -> tuple[BacktestResult, int]:
    n = 120
    periods = [date(2024, 1, 1) + timedelta(days=index) for index in range(n)]
    values = np.full(n, 1.0)

    plan = plan_backtest(n, 4, DAILY, max_folds=6)
    # Every validation point is stamped with the horizon it sits at, so a
    # residual of 3000 can only have come from step 3.
    for cut in plan.cut_points:
        for step in range(plan.horizon):
            values[cut + step] = STEP_MARK * (step + 1)

    if gap_step is not None:
        values[plan.cut_points[-1] + gap_step - 1] = np.nan

    result = run_backtest(lambda _y, _p: Zero(), ModelKind.NAIVE, values, periods, plan, DAILY)
    return result, plan.horizon


class TestAGapDoesNotRenumberTheHorizons:
    def test_the_fold_records_which_steps_it_actually_scored(self) -> None:
        result, _ = _gapped_run(gap_step=2)
        last = result.folds[-1]

        assert last.y_step == [1, 3, 4], "step 2 was never observed, so it is not scored"
        assert len(last.y_true) == 3

    def test_residuals_land_in_the_horizon_they_belong_to(self) -> None:
        result, horizon = _gapped_run(gap_step=2)
        buckets = _residuals_by_step(result, horizon)

        for step, bucket in enumerate(buckets, start=1):
            assert bucket, f"h={step} lost every sample it had"
            for residual in bucket:
                assert (
                    round(residual / STEP_MARK) == step
                ), f"a residual of {residual:.1f} was filed under h={step}"

    def test_the_far_horizon_keeps_its_sample(self) -> None:
        intact, horizon = _gapped_run(gap_step=None)
        gapped, _ = _gapped_run(gap_step=2)

        counts_intact = [len(bucket) for bucket in _residuals_by_step(intact, horizon)]
        counts_gapped = [len(bucket) for bucket in _residuals_by_step(gapped, horizon)]

        assert counts_gapped[-1] == counts_intact[-1], "the last horizon lost a sample"
        assert counts_gapped[1] == counts_intact[1] - 1, "only the gapped step loses one"

    def test_the_conformal_points_carry_the_same_horizons(self) -> None:
        result, _ = _gapped_run(gap_step=2)

        horizons = sorted({point.horizon for point in _held_out(result)})
        by_horizon: dict[int, list[float]] = {}
        for point in _held_out(result):
            by_horizon.setdefault(point.horizon, []).append(point.actual - point.predicted)

        assert horizons == [1, 2, 3, 4]
        for horizon, residuals in by_horizon.items():
            for residual in residuals:
                assert round(residual / STEP_MARK) == horizon


class TestASeasonalScaleSkipsTheGapsRatherThanClosingThem:
    def test_a_hole_does_not_flatter_the_model(self) -> None:
        season = 7
        history = np.array(
            [
                *[10.0, 12.0, 11.0, 13.0, 12.0, 14.0, 13.0],
                *[20.0, 22.0, 21.0, 23.0, 22.0, 24.0, 23.0],
                *[30.0, 32.0, 31.0, 33.0, 32.0, 34.0, 33.0],
            ]
        )
        gapped = history.copy()
        gapped[10] = np.nan

        truth = np.array([40.0, 42.0])
        predicted = np.array([38.0, 44.0])

        intact = mase(truth, predicted, history, season)
        holed = mase(truth, predicted, gapped, season)

        assert intact == pytest.approx(0.2)
        assert holed == pytest.approx(
            intact, abs=0.01
        ), "one unrecorded period must not change how skilful the model looks"

    def test_pairs_that_straddle_a_hole_are_dropped_not_closed_up(self) -> None:
        season = 4
        history = np.array([10.0, 20.0, 30.0, 40.0, 11.0, 21.0, 31.0, 41.0, 12.0, 22.0])
        gapped = history.copy()
        gapped[4] = np.nan

        truth = np.array([50.0])
        predicted = np.array([48.0])

        assert mase(truth, predicted, gapped, season) == pytest.approx(
            mase(truth, predicted, history, season), abs=0.02
        )

    def test_a_history_too_holed_to_pair_at_the_season_falls_back(self) -> None:
        history = np.array([5.0, np.nan, np.nan, np.nan, 9.0, 13.0])

        value = mase(np.array([10.0]), np.array([9.0]), history, 4)

        assert np.isfinite(value), "a lag-1 pair still exists and should be used"

    def test_a_history_with_no_usable_pair_at_all_is_unmeasurable(self) -> None:
        history = np.array([5.0, np.nan, np.nan, np.nan, np.nan, np.nan])

        assert np.isnan(mase(np.array([10.0]), np.array([9.0]), history, 4))


class TestANegativeSegmentSurvivesReconciliation:
    def test_a_returns_line_is_not_clipped_away(self) -> None:
        segments = [
            np.array([100.0, 100.0]),
            np.array([60.0, 60.0]),
            np.array([-40.0, -40.0]),
        ]
        total = np.array([120.0, 120.0])
        shares = [0.62, 0.38, -0.25]

        out = reconcile_to_total(segments, total, shares, non_negative=False)

        assert out[2][0] < 0.0, "the returns line must stay negative"
        assert [round(float(v), 6) for v in out[0]] == [100.0, 100.0]
        assert [round(float(v), 6) for v in out[1]] == [60.0, 60.0]
        assert [round(float(v), 6) for v in out[2]] == [-40.0, -40.0]

    def test_it_still_adds_up_to_the_total(self) -> None:
        segments = [np.array([90.0]), np.array([-30.0])]
        total = np.array([60.0])

        out = reconcile_to_total(segments, total, [0.9, -0.3], non_negative=False)

        assert float(np.sum(out, axis=0)[0]) == pytest.approx(60.0)

    def test_a_non_negative_series_is_still_clipped(self) -> None:
        segments = [np.array([100.0]), np.array([-5.0])]

        out = reconcile_to_total(segments, np.array([100.0]), [1.0, 0.0], non_negative=True)

        assert float(out[1][0]) == 0.0

    def test_segments_that_cancel_to_nothing_fall_back_to_shares(self) -> None:
        segments = [np.array([50.0]), np.array([-50.0])]

        out = reconcile_to_total(segments, np.array([10.0]), [0.5, 0.5], non_negative=False)

        assert float(np.sum(out, axis=0)[0]) == pytest.approx(10.0)
        assert all(np.isfinite(path).all() for path in out)

    def test_the_sign_of_the_history_is_what_decides(self) -> None:
        assert all_non_negative([[1.0, 2.0], [0.0, 3.0]]) is True
        assert all_non_negative([[1.0, 2.0], [0.0, -0.5]]) is False
        assert all_non_negative([[np.nan, 1.0]]) is True
        assert all_non_negative([]) is True


class TestAFoldThatCannotBeScoredSaysSo:
    def test_a_gap_in_the_training_window_is_counted_not_skipped(self) -> None:
        n = 120
        periods = [date(2024, 1, 1) + timedelta(days=index) for index in range(n)]
        values = np.full(n, 100.0)
        plan = plan_backtest(n, 4, DAILY, max_folds=6)
        values[plan.cut_points[0] - 2] = np.nan

        result = run_backtest(lambda _y, _p: Flat(), ModelKind.NAIVE, values, periods, plan, DAILY)

        assert result.folds_failed > 0
        assert result.failure_reason is not None
        assert "never recorded" in result.failure_reason

    def test_a_short_forecast_is_a_failure_rather_than_padded(self) -> None:
        class Short(Flat):
            def predict(self, horizon: int, periods: list[date]) -> np.ndarray:
                return np.full(max(horizon - 2, 1), self.level)

        n = 120
        periods = [date(2024, 1, 1) + timedelta(days=index) for index in range(n)]
        values = np.full(n, 100.0)
        plan = plan_backtest(n, 4, DAILY, max_folds=6)

        result = run_backtest(lambda _y, _p: Short(), ModelKind.NAIVE, values, periods, plan, DAILY)

        assert result.failed
        assert result.failure_reason is not None
        assert "step(s) this fold asked for" in result.failure_reason


class TestTheStepsFallBackWhenNothingRecordedThem:
    def test_a_fold_without_recorded_steps_reads_as_consecutive(self) -> None:
        fold = FoldResult(
            fold=0, train_size=10, test_size=3, y_true=[1.0, 2.0, 3.0], y_pred=[1.0, 2.0, 3.0]
        )

        assert fold.steps() == [1, 2, 3]
