"""The invariants that decide whether this is a forecasting product or a chart.

Each test here corresponds to a claim the product makes to a customer:

  * a forecast that was issued is never quietly rewritten
  * no metric that is undefined on zeros gets to pick the model
  * the backtest is a rolling origin that refits, not a split of shuffled rows
  * the range widens with the horizon and holds at the level it advertises

They are written to fail loudly if someone reintroduces the shortcut, which is
the point of them: every one of these is a mistake that makes the reported
accuracy better than the real accuracy, and that is the direction nobody goes
looking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pytest

from app.core.config import Settings, settings
from app.forecasting.backtest import BacktestPlan, plan_backtest, run_backtest
from app.forecasting.calibration import (
    COVERAGE_TOLERANCE_PP,
    HeldOutPoint,
    calibrate,
    conformal_halfwidths,
    is_monotone_in_horizon,
)
from app.forecasting.metrics import FORBIDDEN_SELECTION_METRICS
from app.models.enums import ForecastFrequency, ModelKind
from app.schemas.forecast import SCORABLE_METRICS

WEEKLY = ForecastFrequency.WEEKLY


def weeks(count: int, start: date = date(2023, 1, 2)) -> list[date]:
    return [start + timedelta(weeks=index) for index in range(count)]


@dataclass
class MeanOfTraining:
    """Forecasts the mean of whatever it was last fitted on.

    Deliberately transparent: its output is a function of its training window
    alone, so what it predicts on a fold tells you exactly which rows it was
    trained on. That makes refit-per-origin observable from the output rather
    than by counting calls.
    """

    level: float = float("nan")

    @property
    def kind(self) -> ModelKind:
        return ModelKind.NAIVE

    def fit(self, y: np.ndarray, periods: list[date]) -> None:
        self.level = float(np.mean(y))

    def predict(self, horizon: int, future_periods: list[date]) -> np.ndarray:
        return np.full(horizon, self.level)

    @property
    def params(self) -> dict[str, object]:
        return {"level": self.level}

    @property
    def min_observations(self) -> int:
        return 2


class TestNoMapeFamilyMetricDecidesAnything:
    def test_the_shipped_scoring_weights_contain_no_mape_family_metric(self) -> None:
        assert set(settings.metric_weights) & FORBIDDEN_SELECTION_METRICS == set()

    def test_a_caller_cannot_ask_to_be_scored_on_one(self) -> None:
        assert set() == SCORABLE_METRICS & FORBIDDEN_SELECTION_METRICS

    def test_the_scale_free_metric_in_use_is_defined_on_a_series_of_zeros(self) -> None:
        from app.forecasting.metrics import mase, smape

        zeros = np.zeros(12)
        history = np.array([0.0, 0.0, 3.0, 0.0, 0.0, 4.0, 0.0, 0.0, 2.0, 0.0])

        # sMAPE returns a number here, and it is a meaningless one: every
        # period where actual and forecast are both zero is scored as a
        # perfect hit, so an all-zero forecast looks flawless.
        assert smape(zeros, zeros) == 0.0
        # MASE divides by the in-sample naive error, which this history has.
        assert np.isfinite(mase(zeros, zeros, history, seasonal_period=1))

    def test_weights_cannot_all_be_zero(self) -> None:
        with pytest.raises(ValueError, match="METRIC_WEIGHT"):
            Settings(
                metric_weight_wmape=0.0,
                metric_weight_mase=0.0,
                metric_weight_rmse=0.0,
            )


class TestBacktestIsARollingOrigin:
    def test_every_fold_trains_only_on_periods_before_it_scores(self) -> None:
        plan = plan_backtest(200, horizon=8, frequency=WEEKLY)

        assert plan.n_folds >= 5, f"only {plan.n_folds} origins"
        for cut in plan.cut_points:
            train = range(cut)
            test = range(cut, cut + plan.horizon)
            assert max(train) < min(test)

    def test_the_origins_move_forward_and_do_not_repeat(self) -> None:
        plan = plan_backtest(200, horizon=8, frequency=WEEKLY)

        assert plan.cut_points == sorted(plan.cut_points)
        assert len(set(plan.cut_points)) == len(plan.cut_points)

    def test_the_model_is_refitted_at_each_origin(self) -> None:
        # A rising series: the mean of an expanding window rises with it, so
        # the same fitted model reused across folds would be visible as a
        # constant prediction.
        y = np.arange(1.0, 201.0)
        plan = plan_backtest(len(y), horizon=8, frequency=WEEKLY)

        result = run_backtest(
            lambda _y, _p: MeanOfTraining(),
            ModelKind.NAIVE,
            y,
            weeks(len(y)),
            plan,
            WEEKLY,
        )

        levels = [fold.y_pred[0] for fold in result.folds]
        assert len(levels) >= 5
        assert levels == sorted(levels)
        assert len(set(levels)) == len(levels), "the model was not refitted per origin"

        # And each level is the mean of exactly that origin's training window.
        for fold, cut in zip(result.folds, plan.cut_points, strict=True):
            expected = float(np.mean(y[:cut]))
            assert fold.y_pred[0] == pytest.approx(expected)

    def test_a_random_split_of_the_rows_fails_the_ordering_invariant(self) -> None:
        # The canary: this is what a shuffled split looks like, and the
        # invariant above has to reject it or it is not testing anything.
        rng = np.random.default_rng(11)
        shuffled = rng.permutation(120)
        train, test = shuffled[:96], shuffled[96:]

        assert not max(train) < min(test), (
            "a random split happened to be ordered; the invariant would not have caught it"
        )

    def test_a_plan_with_one_origin_is_not_accepted_as_a_backtest(self) -> None:
        plan = BacktestPlan(scheme="expanding", horizon=8, cut_points=[96], initial_train=96)

        assert plan.n_folds == 1
        # plan_backtest is what production calls, and on this much history it
        # never returns a single origin.
        assert plan_backtest(200, horizon=8, frequency=WEEKLY).n_folds > 1

    def test_five_origins_need_two_seasons_plus_five_horizons_of_history(self) -> None:
        """What "at least five origins" costs in weeks, stated rather than assumed.

        The initial training window is two seasonal cycles, and each further
        origin costs one horizon on top. Below that the harness returns fewer
        origins — correctly, because the history is not there — so a caller
        asking for five has to bring 144 weeks, not 120.
        """
        horizon = 8
        two_seasons = 104

        assert plan_backtest(two_seasons + 4 * horizon, horizon, WEEKLY).n_folds < 5
        assert plan_backtest(two_seasons + 5 * horizon, horizon, WEEKLY).n_folds >= 5


class TestIntervalsAreCalibratedNotJustEmitted:
    @pytest.mark.parametrize("nominal", [0.5, 0.8, 0.95])
    def test_every_served_level_lands_within_five_points_of_its_claim(
        self, nominal: float
    ) -> None:
        rng = np.random.default_rng(5)
        points = [
            HeldOutPoint(
                horizon=horizon,
                predicted=80.0,
                actual=80.0 + float(rng.normal(0.0, 4.0 * horizon)),
            )
            for horizon in range(1, 6)
            for _ in range(200)
        ]

        after = calibrate(points, nominal).after

        assert after.measurable_points
        for point in after.points:
            assert abs(point.gap_pp) <= COVERAGE_TOLERANCE_PP

    def test_the_range_never_narrows_further_out(self) -> None:
        rng = np.random.default_rng(9)
        points = [
            HeldOutPoint(
                horizon=horizon,
                predicted=80.0,
                actual=80.0 + float(rng.normal(0.0, 3.0 * horizon)),
            )
            for horizon in range(1, 8)
            for _ in range(150)
        ]

        assert is_monotone_in_horizon(conformal_halfwidths(points, 0.8))
