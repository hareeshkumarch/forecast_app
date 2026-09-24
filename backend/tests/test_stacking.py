import numpy as np
import pytest

from app.forecasting.combination import (
    _align,
    _member_errors,
    blend,
    inverse_error_weights,
    stacking_weights,
)
from app.models.enums import ModelKind
from tests.test_selection_honesty import _member


def test_stacking_improves_over_inverse_error_weights_on_complementary_patterns() -> None:
    truth = [[100.0] * 6] * 4
    left = _member(ModelKind.NAIVE, [[110.0, 100.0] * 3] * 4, truth)
    right = _member(ModelKind.THETA, [[80.0, 105.0] * 3] * 4, truth)
    aligned = _align([left, right])
    assert aligned is not None
    baseline = inverse_error_weights(_member_errors(aligned, before=3))
    learned = stacking_weights(aligned, before=3)
    held_out = np.array([left.folds[3].y_pred, right.folds[3].y_pred]).T
    baseline_error = np.mean(np.abs(held_out @ baseline - 100.0))
    learned_error = np.mean(np.abs(held_out @ learned - 100.0))
    assert learned_error < baseline_error * 0.8


def test_stacking_learns_complementary_errors_without_future_folds() -> None:
    truth = [[100.0] * 6] * 4
    left = _member(ModelKind.NAIVE, [[110.0] * 6] * 4, truth)
    right = _member(ModelKind.THETA, [[80.0] * 6] * 4, truth)
    aligned = _align([left, right])
    assert aligned is not None
    weights = stacking_weights(aligned, before=3)
    assert sum(weights) == pytest.approx(1.0)
    assert all(0 <= weight <= 1 for weight in weights)
    assert weights[0] == pytest.approx(2 / 3, abs=0.02)
    left.folds[-1].y_pred = [10000.0] * 6
    changed = _align([left, right])
    assert changed is not None
    assert stacking_weights(changed, before=3) == pytest.approx(weights)
    assert stacking_weights(changed, before=0) == [0.5, 0.5]


@pytest.mark.parametrize("field", ["y_true", "y_step", "y_weight", "y_pred"])
def test_stacking_refuses_misaligned_or_nonfinite_folds(field: str) -> None:
    left = _member(ModelKind.NAIVE, [[11.0, 12.0]], [[10.0, 10.0]])
    right = _member(ModelKind.THETA, [[9.0, 8.0]], [[10.0, 10.0]])
    replacement = {
        "y_true": [10.0, 11.0],
        "y_step": [1, 3],
        "y_weight": [1.0, 2.0],
        "y_pred": [float("nan"), 8.0],
    }
    setattr(right.folds[0], field, replacement[field])
    assert _align([left, right]) is None


def test_zero_demand_can_still_use_an_accurate_blend() -> None:
    left = _member(ModelKind.NAIVE, [[1.0] * 6] * 3, [[0.0] * 6] * 3)
    right = _member(ModelKind.THETA, [[-1.0] * 6] * 3, [[0.0] * 6] * 3)
    left.wmape = right.wmape = float("nan")
    combined = blend([left, right], insample=np.zeros(30))
    assert combined is not None
    assert combined.result.mae == pytest.approx(0.0)


def test_blend_must_beat_members_on_the_same_periods() -> None:
    left = _member(ModelKind.NAIVE, [[1000.0] * 6, [10.0] * 6], [[10.0] * 6] * 2)
    right = _member(ModelKind.THETA, [[9.0] * 6, [9.0] * 6], [[10.0] * 6] * 2)
    right.folds = right.folds[1:]
    assert blend([left, right], insample=np.ones(30)) is None
