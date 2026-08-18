"""Ranking candidates on what was actually measured.

Four ways the comparison was quietly wrong: a metric the run had decided not
to use could still veto a model, a level nobody tabulated was scored as 80%,
the ensemble was weighed using the folds it was about to be judged on, and one
bad fold threw away a model that fitted everywhere else.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.forecasting import combination
from app.forecasting.backtest import (
    BacktestPlan,
    BacktestResult,
    FoldResult,
    normal_quantile,
    run_backtest,
)
from app.forecasting.models import Forecaster
from app.forecasting.scenarios import build_intervals
from app.forecasting.selection import INTERMITTENT_METRIC_WEIGHTS, select_model
from app.models.enums import ForecastFrequency, ModelKind

MONTHLY = ForecastFrequency.MONTHLY


def _result(
    model: ModelKind,
    *,
    wmape: float = 10.0,
    mae: float = 5.0,
    rmse: float = 7.0,
    smape: float = 10.0,
    folds: int = 3,
) -> BacktestResult:
    result = BacktestResult(model=model)
    result.wmape, result.mae, result.rmse, result.smape = wmape, mae, rmse, smape
    result.mase = 1.0
    result.folds = [
        FoldResult(fold=i, train_size=10, test_size=2, y_true=[1.0, 2.0], y_pred=[1.0, 2.0])
        for i in range(folds)
    ]
    return result


# --------------------------------------------------- a metric the run is not using


def test_a_model_is_not_vetoed_by_a_metric_the_run_does_not_score_by() -> None:
    """On intermittent demand the validation windows can total zero, so wMAPE
    is undefined — and Croston, the model that exists for exactly that series,
    was dropped before selection began by a metric the run had already decided
    against."""
    croston = _result(ModelKind.CROSTON, wmape=float("nan"), mae=2.0, rmse=3.0)
    naive = _result(ModelKind.NAIVE, wmape=float("nan"), mae=9.0, rmse=11.0)

    selection = select_model([croston, naive], metric_weights=dict(INTERMITTENT_METRIC_WEIGHTS))

    assert selection.winner is not None
    assert selection.winner.result.model is ModelKind.CROSTON


def test_a_candidate_with_no_usable_metric_at_all_is_still_dropped() -> None:
    lost = _result(ModelKind.NAIVE, wmape=float("nan"), mae=float("nan"), rmse=float("nan"))
    fine = _result(ModelKind.THETA, wmape=float("nan"), mae=4.0, rmse=5.0)

    selection = select_model([lost, fine], metric_weights=dict(INTERMITTENT_METRIC_WEIGHTS))

    assert selection.winner is not None
    assert selection.winner.result.model is ModelKind.THETA


def test_the_rationale_says_it_in_a_measure_the_run_actually_has() -> None:
    croston = _result(ModelKind.CROSTON, wmape=float("nan"), mae=2.0, rmse=3.0)

    selection = select_model([croston], metric_weights=dict(INTERMITTENT_METRIC_WEIGHTS))

    assert "nan" not in selection.rationale.lower()


# ------------------------------------------------------------- the actual level


@pytest.mark.parametrize(
    ("level", "expected"),
    [(0.5, 0.6745), (0.8, 1.2816), (0.9, 1.6449), (0.95, 1.9600), (0.99, 2.5758)],
)
def test_the_tabulated_levels_are_reproduced_exactly(level: float, expected: float) -> None:
    assert normal_quantile(level) == pytest.approx(expected, abs=5e-5)


def test_a_level_nobody_tabulated_is_not_scored_as_eighty_percent() -> None:
    """The table answered anything it did not have with the 80% z, so a 92%
    interval was costed as though it were an 80% one."""
    assert normal_quantile(0.92) != pytest.approx(normal_quantile(0.8))
    assert normal_quantile(0.8) < normal_quantile(0.92) < normal_quantile(0.95)


# ------------------------------------------------------------- the ensemble


def _member(model: ModelKind, per_fold: list[list[float]], truth: list[list[float]]):
    result = BacktestResult(model=model)
    result.folds = [
        FoldResult(
            fold=index,
            train_size=10,
            test_size=len(actual),
            y_true=list(actual),
            y_pred=list(predicted),
        )
        for index, (predicted, actual) in enumerate(zip(per_fold, truth, strict=True))
    ]
    errors = [
        abs(p - a)
        for fold, actual in zip(per_fold, truth, strict=True)
        for p, a in zip(fold, actual, strict=True)
    ]
    result.mae = float(np.mean(errors))
    result.wmape = 10.0
    result.rmse = float(np.sqrt(np.mean([e**2 for e in errors])))
    result.smape = 10.0
    result.mase = 1.0
    return result


def test_the_weights_a_fold_is_scored_under_never_saw_that_fold() -> None:
    """Weighing the members by an error that includes the fold being scored
    tunes the combination on the window it is about to be judged over — so the
    ensemble beats its own best member on paper more often than in use, and
    that comparison is what decides whether it is offered at all.

    One member is exact on the last fold and badly wrong elsewhere; the other
    is the reverse. Whole-backtest weights would trust each one exactly where
    it happens to be right, which is the flattery.
    """
    truth = [[10.0, 10.0], [10.0, 10.0], [10.0, 10.0]]
    left = _member(ModelKind.THETA, [[10.0, 10.0], [10.0, 10.0], [30.0, 30.0]], truth)
    right = _member(ModelKind.NAIVE, [[30.0, 30.0], [30.0, 30.0], [10.0, 10.0]], truth)

    aligned = combination._align([left, right])
    assert aligned is not None

    everything = combination._member_errors(aligned)
    without_last = combination._member_errors(aligned, skip=2)

    # Left is wrong only on the last fold, so leaving it out makes left look
    # perfect and right look worse — the opposite of what the all-folds
    # numbers say, which is the whole point.
    assert everything[0] < everything[1]
    assert without_last[0] == pytest.approx(0.0)
    assert without_last[1] > without_last[0]

    scored_under = combination.inverse_error_weights(without_last)
    assert scored_under[0] > scored_under[1]


def test_a_member_that_is_useless_everywhere_gets_little_weight() -> None:
    truth = [[10.0, 10.0]] * 4
    good = _member(ModelKind.THETA, [[10.0, 10.0]] * 4, truth)
    bad = _member(ModelKind.NAIVE, [[100.0, 100.0]] * 4, truth)

    aligned = combination._align([good, bad])
    assert aligned is not None

    share = combination.inverse_error_weights(combination._member_errors(aligned, skip=0))

    assert share[0] > share[1]


# -------------------------------------------------------------- a failed fold


class _FailsEarly(Forecaster):
    kind = ModelKind.SARIMAX
    min_observations = 1

    def __init__(self, seen: list[int]) -> None:
        self._seen = seen
        self._last = 0.0

    def fit(self, y, periods=None):  # type: ignore[no-untyped-def]
        self._seen.append(int(np.asarray(y).size))
        if np.asarray(y).size < 15:
            raise RuntimeError("failed to converge")
        self._last = float(y[-1])
        return self

    def predict(self, horizon, periods=None):  # type: ignore[no-untyped-def]
        return np.full(horizon, self._last)

    @property
    def params(self) -> dict[str, object]:
        return {}


def _calendar(n: int):
    from datetime import date

    from app.forecasting.frequency import add_periods

    return [add_periods(date(2022, 1, 1), i, MONTHLY) for i in range(n)]


def test_a_model_that_fails_one_fold_is_still_measured_on_the_rest() -> None:
    """SARIMAX fails to converge on the shortest early window and fits every
    later one. Discarding the candidate outright threw away the model that
    would have won, and reported one fold's reason as the whole story."""
    y = np.arange(30, dtype=float) * 10.0
    seen: list[int] = []

    result = run_backtest(
        lambda _y, _p: _FailsEarly(seen),
        ModelKind.SARIMAX,
        y,
        _calendar(30),
        BacktestPlan(scheme="expanding", horizon=3, cut_points=[12, 18, 24], initial_train=12),
        MONTHLY,
    )

    assert not result.failed, result.failure_reason
    assert result.n_folds == 2, "the two folds it could fit"
    assert result.folds_failed == 1
    assert math.isfinite(result.wmape)


def test_a_model_that_fails_most_folds_is_not_ranked_on_the_easy_ones() -> None:
    y = np.arange(30, dtype=float) * 10.0

    result = run_backtest(
        lambda _y, _p: _FailsEarly([]),
        ModelKind.SARIMAX,
        y,
        _calendar(30),
        BacktestPlan(scheme="expanding", horizon=2, cut_points=[6, 8, 10, 12, 20], initial_train=6),
        MONTHLY,
    )

    assert result.failed
    assert result.failure_reason is not None
    assert "too little to compare" in result.failure_reason


# ---------------------------------------------------------- an interval that leans


def test_an_interval_leans_the_way_the_model_has_been_wrong() -> None:
    """Centring the residuals threw away the one thing an empirical interval
    knows that a formula does not. A model that forecast low in every fold will
    forecast low again, and a band centred on it covers the truth from one side
    while claiming to do it from both."""
    biased = BacktestResult(model=ModelKind.NAIVE)
    biased.folds = [
        FoldResult(
            fold=index,
            train_size=20,
            test_size=4,
            y_true=[120.0, 122.0, 118.0, 121.0],
            y_pred=[100.0, 100.0, 100.0, 100.0],
        )
        for index in range(4)
    ]
    biased.wmape = 17.0

    bands = build_intervals(np.full(4, 100.0), biased, 0.8, history=np.full(24, 110.0))

    above = float(np.mean(bands.upper - 100.0))
    below = float(np.mean(100.0 - bands.lower))

    assert above > below, (
        "the model has under-forecast by about 20 every time, so the room "
        "above the point forecast has to be the larger side"
    )
    assert below > 0.0, (
        "and the smaller side still has to exist: clamping it to zero produced "
        "a lower bound equal to the point forecast, which claims demand cannot "
        "come in under the number"
    )
    assert float(np.min(bands.lower)) < 100.0
    assert float(np.min(bands.worst_case)) < 100.0
