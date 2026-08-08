from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from app.forecasting.selection import INTERMITTENT_METRIC_WEIGHTS
from app.forecasting.tuning import (
    SearchSpace,
    blended_error,
    cache_key,
    evaluation_budget,
    tune,
    validation_splits,
)


def _linear_problem(n_rows: int = 120) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(1)
    matrix = rng.normal(0, 1, (n_rows, 3))
    target = matrix @ np.array([2.0, -1.0, 0.5]) + rng.normal(0, 0.1, n_rows)
    return matrix, target


def test_budget_grows_with_history_but_stays_bounded() -> None:
    assert evaluation_budget(24, 100) >= 4
    assert evaluation_budget(10_000, 100) <= 24
    assert evaluation_budget(10_000, 6) == 6


def test_validation_splits_are_chronological_and_disjoint() -> None:
    splits = validation_splits(240, 6)

    assert len(splits) >= 2
    assert all(start < end for start, end in splits)
    for (_, first_end), (second_start, _) in pairwise(splits):
        assert first_end <= second_start


def test_short_history_skips_tuning_rather_than_overfitting() -> None:
    matrix, target = _linear_problem(8)
    space = SearchSpace({"scale": [0.5, 1.0, 2.0]})

    result = tune("linear", matrix, target, space, lambda *_: np.zeros(1), 6)

    assert result.method == "defaults_short_history"
    assert result.evaluations == 0


def test_tuning_picks_the_parameter_that_validates_best() -> None:
    matrix, target = _linear_problem()
    space = SearchSpace({"scale": [0.1, 1.0, 10.0]})

    def fit_predict(params: dict[str, object], start: int, end: int) -> np.ndarray:
        coefficients = np.linalg.lstsq(matrix[:start], target[:start], rcond=None)[0]
        return matrix[start:end] @ coefficients * float(params["scale"])  # type: ignore[arg-type]

    result = tune("scaled_linear", matrix, target, space, fit_predict, 6)

    assert result.params["scale"] == 1.0, "only the unscaled fit reproduces the target"
    assert result.evaluations == 3
    assert result.folds >= 1
    assert np.isfinite(result.score)


def test_repeated_tuning_is_served_from_cache() -> None:
    matrix, target = _linear_problem()
    space = SearchSpace({"scale": [0.1, 1.0, 10.0]})
    calls = {"n": 0}

    def fit_predict(params: dict[str, object], start: int, end: int) -> np.ndarray:
        calls["n"] += 1
        coefficients = np.linalg.lstsq(matrix[:start], target[:start], rcond=None)[0]
        return matrix[start:end] @ coefficients * float(params["scale"])  # type: ignore[arg-type]

    first = tune("cached", matrix, target, space, fit_predict, 6)
    after_first = calls["n"]
    second = tune("cached", matrix, target, space, fit_predict, 6)

    assert calls["n"] == after_first, "a repeated search must not refit"
    assert second.params == first.params


def test_a_failing_candidate_does_not_sink_the_search() -> None:
    matrix, target = _linear_problem()
    space = SearchSpace({"mode": ["broken", "good"]})

    def fit_predict(params: dict[str, object], start: int, end: int) -> np.ndarray:
        if params["mode"] == "broken":
            raise RuntimeError("did not converge")
        coefficients = np.linalg.lstsq(matrix[:start], target[:start], rcond=None)[0]
        return matrix[start:end] @ coefficients

    result = tune("resilient", matrix, target, space, fit_predict, 6)
    assert result.params["mode"] == "good"
    assert result.evaluations == 1, "one of the two candidates produced a score"


def test_a_search_where_nothing_fitted_says_so() -> None:
    """It used to report the number of candidates *tried*, so a search in which
    every fit raised looked like a search that ran — and the defaults it fell
    back to looked like a winner that had been measured."""
    matrix, target = _linear_problem()
    space = SearchSpace({"mode": ["broken", "also_broken"]})

    def always_fails(_params: dict[str, object], _start: int, _end: int) -> np.ndarray:
        raise RuntimeError("did not converge")

    result = tune("hopeless", matrix, target, space, always_fails, 6)

    assert result.evaluations == 0
    assert result.method == "defaults_all_candidates_failed"
    assert not np.isfinite(result.score)


# ------------------------------------------------------------------ cache key


def test_two_feature_sets_over_the_same_target_are_different_searches() -> None:
    """Hashing only the shape meant adding or dropping a driver column — which
    changes the features and not their shape — was answered out of the cache
    with the other one's hyperparameters."""
    _matrix, target = _linear_problem()
    rng = np.random.default_rng(7)
    left = rng.normal(0, 1, (120, 3))
    right = rng.normal(0, 1, (120, 3))
    space = SearchSpace({"scale": [0.1, 1.0]})

    assert cache_key("gbm", left, target, space, 6) != cache_key("gbm", right, target, space, 6)


def test_two_search_spaces_with_the_same_keys_are_different_searches() -> None:
    matrix, target = _linear_problem()

    narrow = SearchSpace({"scale": [0.1, 1.0]})
    wide = SearchSpace({"scale": [0.1, 1.0, 10.0, 100.0]})

    assert cache_key("gbm", matrix, target, narrow, 6) != cache_key("gbm", matrix, target, wide, 6)


def test_the_horizon_is_part_of_the_search() -> None:
    matrix, target = _linear_problem()
    space = SearchSpace({"scale": [0.1, 1.0]})

    assert cache_key("gbm", matrix, target, space, 3) != cache_key("gbm", matrix, target, space, 12)


def test_the_same_search_is_the_same_key() -> None:
    matrix, target = _linear_problem()
    space = SearchSpace({"scale": [0.1, 1.0]})

    assert cache_key("gbm", matrix, target, space, 6) == cache_key(
        "gbm", matrix.copy(), target.copy(), SearchSpace({"scale": [0.1, 1.0]}), 6
    )


# ------------------------------------------------------------------- objective


def test_the_search_scores_by_the_metrics_the_run_scores_by() -> None:
    """A percentage error rewards forecasting zero on an intermittent series,
    which is exactly why the run stops scoring one that way. Tuning that keeps
    using it hands over the parameters that were best at the wrong thing.

    sMAPE puts the all-zero forecast ahead of the honest one here — it scores a
    zero against a zero as perfect and a small number against a zero as 200%
    wrong. The absolute metrics an intermittent run actually uses do not.
    """
    actual = np.array([0.0, 0.0, 10.0, 0.0, 0.0, 8.0])
    all_zeros = np.zeros(6)
    honest = np.array([1.0, 1.0, 7.0, 1.0, 1.0, 6.0])

    percentage = {"smape": 1.0}
    absolute = dict(INTERMITTENT_METRIC_WEIGHTS)

    assert blended_error(actual, all_zeros, percentage) < blended_error(actual, honest, percentage)
    assert blended_error(actual, honest, absolute) < blended_error(actual, all_zeros, absolute)


def test_no_weights_falls_back_to_the_plain_error() -> None:
    actual = np.array([10.0, 20.0, 30.0])
    predicted = np.array([11.0, 19.0, 31.0])

    assert blended_error(actual, predicted, None) == pytest.approx(
        blended_error(actual, predicted, {})
    )
