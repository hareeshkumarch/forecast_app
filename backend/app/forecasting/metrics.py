from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


def _aligned(y_true: FloatArray, y_pred: FloatArray) -> tuple[FloatArray, FloatArray]:
    y_true = np.asarray(y_true, dtype=float).ravel()
    y_pred = np.asarray(y_pred, dtype=float).ravel()
    if y_true.shape != y_pred.shape:
        raise ValueError(f"Shape mismatch: {y_true.shape} vs {y_pred.shape}")
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    return y_true[mask], y_pred[mask]


def mae(y_true: FloatArray, y_pred: FloatArray) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")
    return float(np.mean(np.abs(t - p)))


def rmse(y_true: FloatArray, y_pred: FloatArray) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean((t - p) ** 2)))


def smape(y_true: FloatArray, y_pred: FloatArray) -> float:
    """Kept for display beside the others; never weighted in selection.

    sMAPE is undefined wherever an actual and its forecast are both zero, and
    on a series that is mostly zeros the periods it *can* score are the
    unrepresentative ones. Ranking candidates on it hands intermittent demand
    to whichever model happened to be measured on the fewest weeks. `mase` is
    the scale-free metric selection uses instead.
    """
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")
    denominator = (np.abs(t) + np.abs(p)) / 2.0
    ratio = np.where(
        denominator == 0, 0.0, np.abs(t - p) / np.where(denominator == 0, 1.0, denominator)
    )
    return float(np.mean(ratio) * 100.0)


def bias(y_true: FloatArray, y_pred: FloatArray) -> float:
    """Signed mean error. Positive means the forecast ran high.

    Tracked apart from the error metrics because it is the actionable half:
    a planner can correct a forecast that is consistently ten per cent over,
    and can do nothing at all about the same magnitude of scatter.
    """
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")
    return float(np.mean(p - t))


def relative_bias(y_true: FloatArray, y_pred: FloatArray) -> float:
    """Signed error as a share of volume, so it reads beside wMAPE."""
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")
    volume = float(np.sum(np.abs(t)))
    if volume == 0:
        return float("nan")
    return float(np.sum(p - t) / volume * 100.0)


def pinball(y_true: FloatArray, y_pred: FloatArray, quantile: float) -> float:
    """Pinball (quantile) loss at one nominal level.

    The loss a quantile forecast is actually optimising: being under the
    actual costs `q` per unit and being over costs `1 - q`, so the minimiser
    of the expected loss is the true q-th quantile. This is what makes it a
    proper score for an interval bound, where an error metric on the bound is
    not.
    """
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")
    level = min(max(float(quantile), 0.0), 1.0)
    delta = t - p
    return float(np.mean(np.maximum(level * delta, (level - 1.0) * delta)))


def crps_from_quantiles(
    y_true: FloatArray,
    quantile_forecasts: dict[float, FloatArray],
) -> float:
    """CRPS approximated by averaging pinball loss over the served quantiles.

    The mean pinball loss across evenly spaced quantiles converges to CRPS as
    the grid fills in, so the whole predictive distribution is scored rather
    than a point out of the middle of it. With an uneven grid each level is
    weighted by the span it represents.
    """
    levels = sorted(quantile_forecasts)
    if not levels:
        return float("nan")

    losses: list[float] = []
    weights: list[float] = []
    for index, level in enumerate(levels):
        loss = pinball(y_true, quantile_forecasts[level], level)
        if not np.isfinite(loss):
            continue
        lower = levels[index - 1] if index > 0 else 0.0
        upper = levels[index + 1] if index + 1 < len(levels) else 1.0
        losses.append(loss)
        weights.append((upper - lower) / 2.0)

    if not losses:
        return float("nan")

    total = float(np.sum(weights))
    if total <= 0:
        return float(np.mean(losses))
    return float(np.sum(np.asarray(losses) * np.asarray(weights)) / total) * 2.0


def coverage(y_true: FloatArray, lower: FloatArray, upper: FloatArray) -> float:
    """The share of actuals that landed inside the interval, as a percentage."""
    t = np.asarray(y_true, dtype=float).ravel()
    lo = np.asarray(lower, dtype=float).ravel()
    hi = np.asarray(upper, dtype=float).ravel()
    if t.shape != lo.shape or t.shape != hi.shape:
        raise ValueError("bounds must match the length of y_true")

    mask = np.isfinite(t) & np.isfinite(lo) & np.isfinite(hi)
    if not np.any(mask):
        return float("nan")
    inside = (t[mask] >= lo[mask]) & (t[mask] <= hi[mask])
    return float(np.mean(inside) * 100.0)


def forecast_value_add(model_error: float, baseline_error: float) -> float:
    """How much better than the baseline the model was, as a percentage.

    Positive is an improvement. Negative means the baseline should ship —
    which is the answer this exists to be able to give.
    """
    if not np.isfinite(model_error) or not np.isfinite(baseline_error):
        return float("nan")
    if baseline_error == 0:
        return float("nan")
    return float((baseline_error - model_error) / abs(baseline_error) * 100.0)


def wmape(y_true: FloatArray, y_pred: FloatArray, weights: FloatArray | None = None) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")

    if weights is None:
        w = np.ones_like(t)
    else:
        w = np.asarray(weights, dtype=float).ravel()
        if w.size != t.size:
            raw_true = np.asarray(y_true, dtype=float).ravel()
            raw_pred = np.asarray(y_pred, dtype=float).ravel()
            mask = np.isfinite(raw_true) & np.isfinite(raw_pred)
            if w.size != mask.size:
                raise ValueError("weights must match the length of y_true")
            w = w[mask]
        w = np.where(np.isfinite(w), w, 0.0)

    denominator = float(np.sum(w * np.abs(t)))
    if denominator == 0:
        return float("nan")
    return float(np.sum(w * np.abs(t - p)) / denominator * 100.0)


def mase(
    y_true: FloatArray,
    y_pred: FloatArray,
    insample: FloatArray,
    seasonal_period: int = 1,
) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")

    history = np.asarray(insample, dtype=float).ravel()
    history = history[np.isfinite(history)]
    lag = max(1, int(seasonal_period))
    if history.size <= lag:
        lag = 1
    if history.size <= lag:
        return float("nan")

    scale = float(np.mean(np.abs(history[lag:] - history[:-lag])))
    if not np.isfinite(scale) or scale == 0.0:
        return float("nan")

    return float(np.mean(np.abs(t - p)) / scale)


def winkler(
    y_true: FloatArray,
    lower: FloatArray,
    upper: FloatArray,
    confidence_level: float,
) -> float:
    t = np.asarray(y_true, dtype=float).ravel()
    lo = np.asarray(lower, dtype=float).ravel()
    hi = np.asarray(upper, dtype=float).ravel()
    if t.shape != lo.shape or t.shape != hi.shape:
        raise ValueError("bounds must match the length of y_true")

    mask = np.isfinite(t) & np.isfinite(lo) & np.isfinite(hi)
    if not np.any(mask):
        return float("nan")

    t, lo, hi = t[mask], lo[mask], hi[mask]
    alpha = max(1e-6, 1.0 - float(confidence_level))
    penalty = 2.0 / alpha

    width = hi - lo
    below = np.where(t < lo, penalty * (lo - t), 0.0)
    above = np.where(t > hi, penalty * (t - hi), 0.0)
    return float(np.mean(width + below + above))


def accuracy_from_wmape(value: float) -> float:
    if not np.isfinite(value) or value >= 100.0:
        return float("nan")
    return float(100.0 - value)


FLOAT_TOLERANCE = 1e-9


def intervals_held(coverage: float | None, confidence_level: float | None) -> bool | None:
    if coverage is None or confidence_level is None:
        return None
    return coverage + FLOAT_TOLERANCE >= confidence_level * 100.0


#: Metrics that must never carry weight in model selection. MAPE and sMAPE
#: are undefined on zeros and rank models backwards on exactly the
#: intermittent series the classifier exists to find. Asserted in CI.
FORBIDDEN_SELECTION_METRICS = frozenset({"mape", "smape", "wmape_symmetric"})


def evaluate(
    y_true: FloatArray,
    y_pred: FloatArray,
    weights: FloatArray | None = None,
) -> dict[str, float]:
    return {
        "mae": mae(y_true, y_pred),
        "rmse": rmse(y_true, y_pred),
        "smape": smape(y_true, y_pred),
        "wmape": wmape(y_true, y_pred, weights),
        "bias": bias(y_true, y_pred),
        "relative_bias": relative_bias(y_true, y_pred),
    }
