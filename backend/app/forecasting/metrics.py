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
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")
    denominator = (np.abs(t) + np.abs(p)) / 2.0
    ratio = np.where(
        denominator == 0, 0.0, np.abs(t - p) / np.where(denominator == 0, 1.0, denominator)
    )
    return float(np.mean(ratio) * 100.0)


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
    """
    Error against the naive forecast a person would have made for free.

    The metric that still means something where wMAPE gives up. wMAPE divides
    by the size of the actuals, so a month of no sales sends it past 100% and
    `accuracy_from_wmape` correctly refuses to report an accuracy — leaving
    intermittent series with a dash and nothing else. MASE divides by how well
    a seasonal-naive forecast did on the *training* history instead, a
    denominator that does not collapse.

    1.0 means "no better than repeating last season". Below 1.0 the model is
    earning its place; above it, it is not.
    """
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
        # A perfectly flat history: the naive forecast was exactly right, so
        # there is no scale to be wrong against.
        return float("nan")

    return float(np.mean(np.abs(t - p)) / scale)


def winkler(
    y_true: FloatArray,
    lower: FloatArray,
    upper: FloatArray,
    confidence_level: float,
) -> float:
    """
    What an interval costs: its width, plus a penalty for what it missed.

    Point error alone cannot tell an honest interval from a confident one, so
    a model that quotes a narrow band it does not keep scores identically to
    one that admits what it does not know. This is the standard answer: the
    band pays for its own width, and pays `2/(1-confidence)` times the
    distance to any actual that fell outside it — so under-covering is
    expensive in proportion to how bold the claim was.

    Lower is better, and it is in the units of the series.
    """
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
    """
    Accuracy as the complement of the error, where that still means something.

    Past 100% the error is larger than the series it is measured against, and
    "100 minus the error" stops being a scale: a wMAPE of 101% and one of 400%
    both pinned to 0.0%, which reads as a measured zero rather than as the
    measurement having broken down. Intermittent demand lands there routinely —
    a month of no sales makes the denominator tiny — and telling a planner
    their forecast is 0% accurate is both wrong and the opposite of useful.
    Not a number, so the card shows a dash and the error beside it does the
    talking.
    """
    if not np.isfinite(value) or value >= 100.0:
        return float("nan")
    return float(100.0 - value)


#: Slack for comparing two percentages arrived at by different arithmetic.
#: Far below any difference a reader could see.
FLOAT_TOLERANCE = 1e-9


def intervals_held(coverage: float | None, confidence_level: float | None) -> bool | None:
    """
    Whether a prediction interval kept the promise it made.

    Coverage is noisy over a handful of periods, so this asks the weaker
    question a short horizon can actually answer: did at least as many actuals
    land inside as the stated confidence claimed? The tolerance is for float
    comparison alone — four actuals inside five is exactly 80%, and that should
    not fail an 80% interval on the last bit of a double.

    One definition, because the report and the API were each deciding this and
    a run could pass on screen while failing on paper.
    """
    if coverage is None or confidence_level is None:
        return None
    return coverage + FLOAT_TOLERANCE >= confidence_level * 100.0


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
    }
