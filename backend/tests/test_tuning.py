from __future__ import annotations

from itertools import pairwise

import numpy as np

from app.forecasting.tuning import (
    SearchSpace,
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

    def fit_predict(params, train_x, train_y, valid_x):
        coefficients = np.linalg.lstsq(train_x, train_y, rcond=None)[0]
        return valid_x @ coefficients * float(params["scale"])

    result = tune("scaled_linear", matrix, target, space, fit_predict, 6)

    assert result.params["scale"] == 1.0, "only the unscaled fit reproduces the target"
    assert result.evaluations == 3
    assert result.folds >= 1
    assert np.isfinite(result.score)


def test_repeated_tuning_is_served_from_cache() -> None:
    matrix, target = _linear_problem()
    space = SearchSpace({"scale": [0.1, 1.0, 10.0]})
    calls = {"n": 0}

    def fit_predict(params, train_x, train_y, valid_x):
        calls["n"] += 1
        coefficients = np.linalg.lstsq(train_x, train_y, rcond=None)[0]
        return valid_x @ coefficients * float(params["scale"])

    first = tune("cached", matrix, target, space, fit_predict, 6)
    after_first = calls["n"]
    second = tune("cached", matrix, target, space, fit_predict, 6)

    assert calls["n"] == after_first, "a repeated search must not refit"
    assert second.params == first.params


def test_a_failing_candidate_does_not_sink_the_search() -> None:
    matrix, target = _linear_problem()
    space = SearchSpace({"mode": ["broken", "good"]})

    def fit_predict(params, train_x, train_y, valid_x):
        if params["mode"] == "broken":
            raise RuntimeError("did not converge")
        coefficients = np.linalg.lstsq(train_x, train_y, rcond=None)[0]
        return valid_x @ coefficients

    result = tune("resilient", matrix, target, space, fit_predict, 6)
    assert result.params["mode"] == "good"
