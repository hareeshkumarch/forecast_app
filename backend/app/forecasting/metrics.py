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


def bias(y_true: FloatArray, y_pred: FloatArray) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")
    return float(np.mean(p - t))


def relative_bias(y_true: FloatArray, y_pred: FloatArray) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")
    volume = float(np.sum(np.abs(t)))
    if volume == 0:
        return float("nan")
    return float(np.sum(p - t) / volume * 100.0)


def pinball(y_true: FloatArray, y_pred: FloatArray, quantile: float) -> float:
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
    lag = max(1, int(seasonal_period))
    if history.size <= lag:
        lag = 1
    if history.size <= lag:
        return float("nan")

    scale = _seasonal_step(history, lag)
    if not np.isfinite(scale) and lag != 1:
        scale = _seasonal_step(history, 1)
    if not np.isfinite(scale) or scale == 0.0:
        return float("nan")

    return float(np.mean(np.abs(t - p)) / scale)


def _seasonal_step(history: FloatArray, lag: int) -> float:
    if history.size <= lag:
        return float("nan")

    ahead, behind = history[lag:], history[:-lag]
    pairs = np.isfinite(ahead) & np.isfinite(behind)
    if not pairs.any():
        return float("nan")

    return float(np.mean(np.abs(ahead[pairs] - behind[pairs])))


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


def rmsse(
    y_true: FloatArray,
    y_pred: FloatArray,
    insample: FloatArray,
    seasonal_period: int = 1,
) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")

    history = np.asarray(insample, dtype=float).ravel()
    lag = max(1, int(seasonal_period))
    if history.size <= lag:
        lag = 1
    if history.size <= lag:
        return float("nan")

    scale = _squared_seasonal_step(history, lag)
    if not np.isfinite(scale) and lag != 1:
        scale = _squared_seasonal_step(history, 1)
    if not np.isfinite(scale) or scale == 0.0:
        return float("nan")

    return float(np.sqrt(np.mean((t - p) ** 2) / scale))


def _squared_seasonal_step(history: FloatArray, lag: int) -> float:
    if history.size <= lag:
        return float("nan")
    ahead, behind = history[lag:], history[:-lag]
    pairs = np.isfinite(ahead) & np.isfinite(behind)
    if not pairs.any():
        return float("nan")
    return float(np.mean((ahead[pairs] - behind[pairs]) ** 2))


def medae(y_true: FloatArray, y_pred: FloatArray) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size == 0:
        return float("nan")
    return float(np.median(np.abs(t - p)))


def mape(y_true: FloatArray, y_pred: FloatArray) -> float:
    t, p = _aligned(y_true, y_pred)
    usable = t != 0
    if not np.any(usable):
        return float("nan")
    return float(np.mean(np.abs((t[usable] - p[usable]) / t[usable])) * 100.0)


def rmsle(y_true: FloatArray, y_pred: FloatArray) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size == 0 or np.any(t < 0) or np.any(p < 0):
        return float("nan")
    return float(np.sqrt(np.mean((np.log1p(p) - np.log1p(t)) ** 2)))


def theil_u2(
    y_true: FloatArray,
    y_pred: FloatArray,
    insample: FloatArray,
    seasonal_period: int = 1,
) -> float:
    naive = rmsse(y_true, y_pred, insample, seasonal_period)
    if not np.isfinite(naive):
        return float("nan")
    return naive


def r_squared(y_true: FloatArray, y_pred: FloatArray) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size < 2:
        return float("nan")
    total = float(np.sum((t - np.mean(t)) ** 2))
    if total == 0:
        return float("nan")
    return float(1.0 - np.sum((t - p) ** 2) / total)


def residual_acf1(y_true: FloatArray, y_pred: FloatArray) -> float:
    t, p = _aligned(y_true, y_pred)
    if t.size < 3:
        return float("nan")
    residual = t - p
    residual = residual - np.mean(residual)
    denominator = float(np.sum(residual**2))
    if denominator == 0:
        return float("nan")
    return float(np.sum(residual[1:] * residual[:-1]) / denominator)


def interval_skill(
    y_true: FloatArray,
    lower: FloatArray,
    upper: FloatArray,
    insample: FloatArray,
    confidence_level: float,
    seasonal_period: int = 1,
) -> float:
    raw = winkler(y_true, lower, upper, confidence_level)
    if not np.isfinite(raw):
        return float("nan")

    history = np.asarray(insample, dtype=float).ravel()
    lag = max(1, int(seasonal_period))
    if history.size <= lag:
        lag = 1
    scale = _seasonal_step(history, lag)
    if not np.isfinite(scale) and lag != 1:
        scale = _seasonal_step(history, 1)
    if not np.isfinite(scale) or scale == 0.0:
        return float("nan")

    return float(raw / scale)


def accuracy_from_wmape(value: float) -> float:
    if not np.isfinite(value) or value >= 100.0:
        return float("nan")
    return float(100.0 - value)


FLOAT_TOLERANCE = 1e-9


def intervals_held(coverage: float | None, confidence_level: float | None) -> bool | None:
    if coverage is None or confidence_level is None:
        return None
    return coverage + FLOAT_TOLERANCE >= confidence_level * 100.0


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
