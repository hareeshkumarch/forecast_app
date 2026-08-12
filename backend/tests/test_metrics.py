from __future__ import annotations

import math

import numpy as np
import pytest

from app.forecasting.metrics import accuracy_from_wmape, evaluate, mae, rmse, smape, wmape


def test_perfect_forecast_scores_zero_error() -> None:
    y = np.array([100.0, 110.0, 120.0])
    assert mae(y, y) == 0.0
    assert rmse(y, y) == 0.0
    assert smape(y, y) == 0.0
    assert wmape(y, y) == 0.0


def test_known_values() -> None:
    actual = np.array([100.0, 200.0, 300.0])
    predicted = np.array([110.0, 180.0, 330.0])

    assert mae(actual, predicted) == pytest.approx(20.0)
    assert rmse(actual, predicted) == pytest.approx(math.sqrt((100 + 400 + 900) / 3))

    assert wmape(actual, predicted) == pytest.approx(10.0)


def test_nan_pairs_are_ignored_not_zeroed() -> None:
    actual = np.array([100.0, np.nan, 300.0])
    predicted = np.array([110.0, 200.0, 330.0])

    assert mae(actual, predicted) == pytest.approx(20.0)


def test_empty_overlap_returns_nan_not_zero() -> None:
    actual = np.array([np.nan, np.nan])
    predicted = np.array([1.0, 2.0])

    assert math.isnan(mae(actual, predicted))
    assert math.isnan(wmape(actual, predicted))


def test_smape_handles_zero_pairs() -> None:
    actual = np.array([0.0, 100.0])
    predicted = np.array([0.0, 100.0])
    assert smape(actual, predicted) == pytest.approx(0.0)


def test_smape_is_bounded() -> None:
    actual = np.array([100.0, 100.0])
    predicted = np.array([-100.0, -100.0])
    assert 0.0 <= smape(actual, predicted) <= 200.0


def test_wmape_weights_by_volume() -> None:
    actual = np.array([1000.0, 10.0])
    predicted = np.array([900.0, 5.0])

    weighted = wmape(actual, predicted)

    assert weighted == pytest.approx((100 + 5) / 1010 * 100)
    assert weighted < 25.0


def test_wmape_with_explicit_weights() -> None:
    actual = np.array([100.0, 100.0])
    predicted = np.array([90.0, 110.0])
    weights = np.array([1.0, 0.0])

    assert wmape(actual, predicted, weights) == pytest.approx(10.0)


def test_wmape_zero_denominator_returns_nan() -> None:
    actual = np.array([0.0, 0.0])
    predicted = np.array([1.0, 2.0])
    assert math.isnan(wmape(actual, predicted))


def test_accuracy_clamps_at_zero() -> None:
    assert accuracy_from_wmape(9.0) == pytest.approx(91.0)

    # Past 100% the complement is not a scale any more, so there is no number
    # to show rather than a zero that reads as a measurement.
    assert math.isnan(accuracy_from_wmape(250.0))
    assert math.isnan(accuracy_from_wmape(100.0))
    assert accuracy_from_wmape(99.5) == pytest.approx(0.5)
    assert math.isnan(accuracy_from_wmape(float("nan")))


def test_evaluate_returns_all_metrics() -> None:
    actual = np.array([10.0, 20.0, 30.0])
    predicted = np.array([11.0, 19.0, 31.0])
    scores = evaluate(actual, predicted)

    assert set(scores) == {"mae", "rmse", "smape", "wmape", "bias", "relative_bias"}
    assert all(math.isfinite(value) for value in scores.values())


def test_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="Shape mismatch"):
        mae(np.array([1.0, 2.0]), np.array([1.0]))
