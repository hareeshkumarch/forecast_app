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


def accuracy_from_wmape(value: float) -> float:
    if not np.isfinite(value):
        return float("nan")
    return float(max(0.0, 100.0 - value))


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
