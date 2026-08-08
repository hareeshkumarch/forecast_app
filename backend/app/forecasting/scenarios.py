from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy import stats

from app.core.config import settings
from app.forecasting.backtest import BacktestResult

FloatArray = npt.NDArray[np.float64]


MIN_EMPIRICAL_RESIDUALS = 8

FALLBACK_VOLATILITY_WEIGHT = 0.75

MIN_RELATIVE_SIGMA = 1e-9


@dataclass(slots=True)
class IntervalBands:
    lower: FloatArray
    upper: FloatArray
    best_case: FloatArray
    base_case: FloatArray
    worst_case: FloatArray
    sigma_by_step: FloatArray
    method: str


def _residuals_by_step(result: BacktestResult, horizon: int) -> list[list[float]]:
    buckets: list[list[float]] = [[] for _ in range(horizon)]
    for fold in result.folds:
        for step, (actual, predicted) in enumerate(zip(fold.y_true, fold.y_pred, strict=False)):
            if step >= horizon:
                break
            if np.isfinite(actual) and np.isfinite(predicted):
                buckets[step].append(actual - predicted)
    return buckets


def _volatility_sigma(history: FloatArray, horizon: int) -> FloatArray:
    finite = history[np.isfinite(history)]

    scale = 0.0
    if finite.size >= 2:
        steps = np.abs(np.diff(finite))
        scale = float(np.median(steps))
        if scale <= 0.0:
            scale = float(np.mean(steps))
    if scale <= 0.0 and finite.size:
        scale = float(np.max(np.abs(finite))) * 0.1

    return scale * FALLBACK_VOLATILITY_WEIGHT * np.sqrt(np.arange(1, horizon + 1))


def _sigma_by_step(
    result: BacktestResult, horizon: int, history: FloatArray
) -> tuple[FloatArray, str]:
    buckets = _residuals_by_step(result, horizon)
    pooled = [value for bucket in buckets for value in bucket]

    if not pooled:
        return _volatility_sigma(history, horizon), "series_volatility"

    pooled_sigma = float(np.std(pooled, ddof=1)) if len(pooled) > 1 else abs(float(pooled[0]))
    if pooled_sigma == 0.0:
        pooled_sigma = float(np.mean(np.abs(pooled))) or 1e-9

    sigmas = np.zeros(horizon)
    used_empirical = 0
    for step in range(horizon):
        bucket = buckets[step]
        if len(bucket) >= 3:
            sigmas[step] = float(np.std(bucket, ddof=1))
            used_empirical += 1
        else:
            sigmas[step] = pooled_sigma * np.sqrt(step + 1)

    sigmas = np.maximum.accumulate(sigmas)

    method = "empirical_per_step" if used_empirical >= horizon // 2 else "pooled_sqrt_scaled"
    return sigmas, method


def _quantile_offsets(
    result: BacktestResult, horizon: int, coverage: float
) -> tuple[FloatArray, FloatArray] | None:
    buckets = _residuals_by_step(result, horizon)
    pooled = np.array([value for bucket in buckets for value in bucket], dtype=float)
    if pooled.size < MIN_EMPIRICAL_RESIDUALS:
        return None

    tail = (1.0 - coverage) / 2.0
    lower = np.zeros(horizon)
    upper = np.zeros(horizon)

    # The residuals are used as they came out, bias and all. Subtracting their
    # median first was throwing away the one thing an empirical interval knows
    # that a formula does not: a model that has forecast low in every fold will
    # forecast low again, and a band centred on it covers the truth from one
    # side only while claiming to do it from both. Kept as they are, the band
    # leans the way the model has been wrong.
    pooled_low = float(np.quantile(pooled, tail))
    pooled_high = float(np.quantile(pooled, 1.0 - tail))

    if pooled_high - pooled_low <= 0:
        return None

    for step in range(horizon):
        bucket = np.array(buckets[step], dtype=float)
        if bucket.size >= MIN_EMPIRICAL_RESIDUALS:
            step_low = float(np.quantile(bucket, tail))
            step_high = float(np.quantile(bucket, 1.0 - tail))
        else:
            spread = np.sqrt(step + 1)
            step_low, step_high = pooled_low * spread, pooled_high * spread

        lower[step] = min(step_low, 0.0)
        upper[step] = max(step_high, 0.0)

    lower = -np.maximum.accumulate(-lower)
    upper = np.maximum.accumulate(upper)
    return lower, upper


def build_intervals(
    point_forecast: FloatArray,
    backtest: BacktestResult,
    confidence_level: float = 0.8,
    *,
    history: FloatArray | None = None,
    non_negative: bool = False,
) -> IntervalBands:
    point_forecast = np.asarray(point_forecast, dtype=float).ravel()
    horizon = point_forecast.size
    past = (
        np.asarray(history, dtype=float).ravel()
        if history is not None
        else np.empty(0, dtype=float)
    )

    sigmas, method = _sigma_by_step(backtest, horizon, past)

    scenario_confidence = settings.scenario_confidence
    empirical = _quantile_offsets(backtest, horizon, confidence_level)
    scenario = _quantile_offsets(backtest, horizon, scenario_confidence)

    if empirical is not None and scenario is not None:
        interval_low, interval_high = empirical
        scenario_low, scenario_high = scenario
        method = "empirical_quantiles"
    else:
        z_interval = float(stats.norm.ppf(0.5 + confidence_level / 2.0))
        z_scenario = float(stats.norm.ppf(0.5 + scenario_confidence / 2.0))
        interval_low, interval_high = -z_interval * sigmas, z_interval * sigmas
        scenario_low, scenario_high = -z_scenario * sigmas, z_scenario * sigmas

    scenario_low = np.minimum(scenario_low, interval_low)
    scenario_high = np.maximum(scenario_high, interval_high)

    lower = point_forecast + interval_low
    upper = point_forecast + interval_high
    worst = point_forecast + scenario_low
    best = point_forecast + scenario_high

    if method != "no_residuals":
        level = float(np.max(np.abs(point_forecast))) if point_forecast.size else 0.0
        floor = level * MIN_RELATIVE_SIGMA
        collapsed = (upper - lower <= 0.0) & (np.abs(interval_high - interval_low) > 0.0)
        if floor > 0.0 and collapsed.any():
            lower = np.where(collapsed, point_forecast - floor, lower)
            upper = np.where(collapsed, point_forecast + floor, upper)
            worst = np.minimum(worst, lower)
            best = np.maximum(best, upper)

    if non_negative:
        lower = np.maximum(lower, 0.0)
        worst = np.maximum(worst, 0.0)
        worst = np.minimum(worst, lower)

    return IntervalBands(
        lower=lower,
        upper=upper,
        best_case=best,
        base_case=point_forecast.copy(),
        worst_case=worst,
        sigma_by_step=sigmas,
        method=method,
    )
