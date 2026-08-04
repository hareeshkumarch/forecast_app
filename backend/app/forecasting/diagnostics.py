from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from app.forecasting.frequency import candidate_periods, seasonal_period
from app.models.enums import ForecastFrequency

FloatArray = npt.NDArray[np.float64]

SEASONAL_STRENGTH_FLOOR = 0.30
SEASONAL_ACF_FLOOR = 0.20
SEASONAL_DIFFERENCE_FLOOR = 0.64
TREND_STRENGTH_FLOOR = 0.20
INTERMITTENT_ZERO_SHARE = 0.30
MAX_DIFFERENCE_ORDER = 2
BOX_COX_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
LOG_LAMBDA_CEILING = 0.30


@dataclass(slots=True)
class SeriesProfile:
    n_observations: int
    frequency: ForecastFrequency
    seasonal_period: int
    seasonal_strength: float
    seasonal_scores: dict[int, float]
    trend_strength: float
    strictly_positive: bool
    zero_share: float
    intermittent: bool
    coefficient_of_variation: float
    outlier_share: float
    box_cox_lambda: float
    transform: str
    difference_order: int
    seasonal_difference_order: int

    @property
    def has_seasonality(self) -> bool:
        return self.seasonal_period > 1 and self.seasonal_strength >= SEASONAL_STRENGTH_FLOOR

    @property
    def has_trend(self) -> bool:
        return self.trend_strength >= TREND_STRENGTH_FLOOR

    @property
    def seasons_observed(self) -> float:
        if self.seasonal_period <= 1:
            return 0.0
        return self.n_observations / self.seasonal_period

    def as_dict(self) -> dict[str, object]:
        return {
            "n_observations": self.n_observations,
            "seasonal_period": self.seasonal_period,
            "seasonal_strength": round(self.seasonal_strength, 4),
            "trend_strength": round(self.trend_strength, 4),
            "intermittent": self.intermittent,
            "zero_share": round(self.zero_share, 4),
            "outlier_share": round(self.outlier_share, 4),
            "coefficient_of_variation": round(self.coefficient_of_variation, 4),
            "transform": self.transform,
            "box_cox_lambda": round(self.box_cox_lambda, 3),
            "difference_order": self.difference_order,
            "seasonal_difference_order": self.seasonal_difference_order,
        }


@dataclass(slots=True)
class _Decomposition:
    seasonal: FloatArray
    remainder: FloatArray
    detrended: FloatArray
    trend: FloatArray = field(default_factory=lambda: np.array([]))


def _clean(values: FloatArray) -> FloatArray:
    array = np.asarray(values, dtype=float).ravel()
    return array[np.isfinite(array)]


def _centred_moving_average(values: FloatArray, window: int) -> FloatArray:
    n = values.size
    trend = np.full(n, np.nan)
    if window < 2 or n < window:
        return trend

    half = window // 2
    if window % 2 == 0:
        kernel = np.full(window + 1, 1.0 / window)
        kernel[0] = kernel[-1] = 1.0 / (2 * window)
        reach = half
    else:
        kernel = np.full(window, 1.0 / window)
        reach = half

    for index in range(reach, n - reach):
        chunk = values[index - reach : index + reach + 1]
        if chunk.size == kernel.size:
            trend[index] = float(np.dot(chunk, kernel))
    return trend


def _decompose(values: FloatArray, period: int) -> _Decomposition | None:
    if period < 2 or values.size < 2 * period:
        return None

    trend = _centred_moving_average(values, period)
    detrended = values - trend

    seasonal = np.full(values.size, np.nan)
    phase_means = np.full(period, np.nan)
    for phase in range(period):
        phase_values = detrended[phase::period]
        finite = phase_values[np.isfinite(phase_values)]
        if finite.size:
            phase_means[phase] = float(np.mean(finite))

    if not np.any(np.isfinite(phase_means)):
        return None

    phase_means = phase_means - np.nanmean(phase_means)
    for index in range(values.size):
        seasonal[index] = phase_means[index % period]

    remainder = detrended - seasonal
    return _Decomposition(seasonal=seasonal, remainder=remainder, detrended=detrended, trend=trend)


def _variance(values: FloatArray) -> float:
    finite = values[np.isfinite(values)]
    if finite.size < 2:
        return 0.0
    return float(np.var(finite, ddof=1))


def _strength(signal: FloatArray, remainder: FloatArray) -> float:
    mask = np.isfinite(signal) & np.isfinite(remainder)
    if mask.sum() < 3:
        return 0.0

    combined = _variance(signal[mask] + remainder[mask])
    if combined <= 0:
        return 0.0
    return float(np.clip(1.0 - _variance(remainder[mask]) / combined, 0.0, 1.0))


def _autocorrelation(values: FloatArray, lag: int) -> float:
    if values.size <= lag + 2:
        return 0.0

    centred = values - float(np.mean(values))
    denominator = float(np.dot(centred, centred))
    if denominator <= 0:
        return 0.0
    return float(np.dot(centred[lag:], centred[:-lag]) / denominator)


def _repeats_significantly(detrended: FloatArray, period: int) -> bool:
    finite = detrended[np.isfinite(detrended)]
    if finite.size <= period + 2:
        return False

    band = max(SEASONAL_ACF_FLOOR, 2.0 / np.sqrt(finite.size))
    return _autocorrelation(finite, period) >= band


def seasonal_scores(values: FloatArray, frequency: ForecastFrequency) -> dict[int, float]:
    scores: dict[int, float] = {}
    for period in candidate_periods(frequency, values.size):
        decomposition = _decompose(values, period)
        if decomposition is None:
            continue

        strength = _strength(decomposition.seasonal, decomposition.remainder)
        scores[period] = (
            strength if _repeats_significantly(decomposition.detrended, period) else 0.0
        )
    return scores


def _pick_period(scores: dict[int, float], frequency: ForecastFrequency, n: int) -> tuple[int, float]:
    if not scores:
        default = seasonal_period(frequency)
        return (default if n >= 2 * default else 1), 0.0

    best_period = max(scores, key=lambda period: (scores[period], -period))
    best_score = scores[best_period]

    if best_score < SEASONAL_STRENGTH_FLOOR:
        default = seasonal_period(frequency)
        return (default if n >= 2 * default else 1), best_score

    for period in sorted(scores):
        if period < best_period and scores[period] >= best_score - 0.05:
            return period, scores[period]
    return best_period, best_score


def _trend_strength(values: FloatArray, period: int) -> float:
    decomposition = _decompose(values, period) if period >= 2 else None
    if decomposition is None:
        differenced = np.diff(values)
        if differenced.size < 3 or _variance(values) <= 0:
            return 0.0
        return float(np.clip(1.0 - _variance(differenced) / (2.0 * _variance(values)), 0.0, 1.0))

    deseasonalised = values - decomposition.seasonal
    smoothed = _centred_moving_average(deseasonalised, max(3, period | 1))
    remainder = deseasonalised - smoothed
    mask = np.isfinite(smoothed) & np.isfinite(remainder)
    if mask.sum() < 3:
        return 0.0
    return _strength(smoothed[mask] - np.nanmean(smoothed[mask]), remainder[mask])


def _outlier_share(values: FloatArray) -> float:
    if values.size < 5:
        return 0.0

    differenced = np.diff(values)
    median = float(np.median(differenced))
    deviation = float(np.median(np.abs(differenced - median)))
    if deviation <= 0:
        return 0.0

    scaled = np.abs(differenced - median) / (1.4826 * deviation)
    return float(np.mean(scaled > 3.5))


def _box_cox_lambda(values: FloatArray, period: int) -> float:
    if values.size < 8 or np.any(values <= 0):
        return 1.0

    group = max(2, period if period >= 2 else 4)
    groups = [values[start : start + group] for start in range(0, values.size, group)]
    groups = [chunk for chunk in groups if chunk.size >= 2]
    if len(groups) < 2:
        return 1.0

    means = np.array([float(np.mean(chunk)) for chunk in groups])
    deviations = np.array([float(np.std(chunk, ddof=1)) for chunk in groups])
    usable = (means > 0) & np.isfinite(deviations)
    if usable.sum() < 2:
        return 1.0

    means, deviations = means[usable], deviations[usable]

    best_lambda, best_dispersion = 1.0, float("inf")
    for candidate in BOX_COX_GRID:
        ratio = deviations / np.power(means, 1.0 - candidate)
        mean_ratio = float(np.mean(ratio))
        if mean_ratio <= 0 or not np.isfinite(mean_ratio):
            continue
        dispersion = float(np.std(ratio, ddof=1)) / mean_ratio
        if np.isfinite(dispersion) and dispersion < best_dispersion:
            best_lambda, best_dispersion = candidate, dispersion

    return best_lambda


def _difference_order(values: FloatArray, period: int) -> int:
    order = 0
    working = values.copy()

    while order < MAX_DIFFERENCE_ORDER and working.size > max(8, period):
        if _is_stationary(working):
            break
        working = np.diff(working)
        order += 1

    return order


def _is_stationary(values: FloatArray) -> bool:
    if values.size < 8:
        return True

    try:
        from statsmodels.tsa.stattools import kpss

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            statistic, _p_value, _lags, critical = kpss(values, regression="c", nlags="auto")
        return bool(statistic < critical["5%"])
    except Exception:
        return _variance(np.diff(values)) >= _variance(values)


def _seasonal_difference_order(strength: float, seasons: float) -> int:
    if seasons < 2.5:
        return 0
    return 1 if strength >= SEASONAL_DIFFERENCE_FLOOR else 0


def profile_series(values: FloatArray, frequency: ForecastFrequency) -> SeriesProfile:
    finite = _clean(values)
    n = int(finite.size)

    if n == 0:
        return SeriesProfile(
            n_observations=0,
            frequency=frequency,
            seasonal_period=1,
            seasonal_strength=0.0,
            seasonal_scores={},
            trend_strength=0.0,
            strictly_positive=False,
            zero_share=0.0,
            intermittent=False,
            coefficient_of_variation=0.0,
            outlier_share=0.0,
            box_cox_lambda=1.0,
            transform="none",
            difference_order=0,
            seasonal_difference_order=0,
        )

    scores = seasonal_scores(finite, frequency)
    period, strength = _pick_period(scores, frequency, n)

    zero_share = float(np.mean(np.isclose(finite, 0.0)))
    strictly_positive = bool(np.all(finite > 0))
    intermittent = zero_share >= INTERMITTENT_ZERO_SHARE

    mean = float(np.mean(finite))
    deviation = float(np.std(finite, ddof=1)) if n > 1 else 0.0
    cv = abs(deviation / mean) if mean else 0.0

    lambda_hint = _box_cox_lambda(finite, period) if strictly_positive and not intermittent else 1.0
    transform = "log" if strictly_positive and not intermittent and lambda_hint <= LOG_LAMBDA_CEILING else "none"

    seasons = n / period if period > 1 else 0.0

    return SeriesProfile(
        n_observations=n,
        frequency=frequency,
        seasonal_period=period,
        seasonal_strength=strength,
        seasonal_scores=scores,
        trend_strength=_trend_strength(finite, period),
        strictly_positive=strictly_positive,
        zero_share=zero_share,
        intermittent=intermittent,
        coefficient_of_variation=cv,
        outlier_share=_outlier_share(finite),
        box_cox_lambda=lambda_hint,
        transform=transform,
        difference_order=_difference_order(finite, period),
        seasonal_difference_order=_seasonal_difference_order(strength, seasons),
    )


def minimum_history(profile: SeriesProfile) -> int:
    if profile.has_seasonality:
        return max(8, 2 * profile.seasonal_period)
    return max(6, min(12, profile.n_observations))
