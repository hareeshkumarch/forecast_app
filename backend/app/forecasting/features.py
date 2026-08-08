from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import numpy.typing as npt

from app.forecasting.diagnostics import SeriesProfile
from app.forecasting.drivers import DriverPanel
from app.forecasting.frequency import seasonal_period
from app.models.enums import ForecastFrequency

FloatArray = npt.NDArray[np.float64]

DRIVER_PREFIX = "driver_"


@dataclass(slots=True)
class FeatureSpec:
    lags: list[int]
    rolling_windows: list[int]
    use_calendar: bool = True
    use_trend: bool = True
    use_seasonal: bool = True
    seasonal_period: int = 12
    names: list[str] = field(default_factory=list)
    drivers: DriverPanel = field(default_factory=DriverPanel)


def driver_mask(names: list[str]) -> npt.NDArray[np.bool_]:
    return np.array([name.startswith(DRIVER_PREFIX) for name in names], dtype=bool)


def build_feature_spec(
    n_observations: int,
    frequency: ForecastFrequency,
    profile: SeriesProfile | None = None,
    drivers: DriverPanel | None = None,
) -> FeatureSpec:
    period = (
        profile.seasonal_period
        if profile and profile.seasonal_period > 1
        else seasonal_period(frequency)
    )
    seasonal = profile.has_seasonality if profile is not None else n_observations >= 2 * period + 4

    lags = [1, 2, 3]

    if seasonal and n_observations >= 2 * period + 4:
        lags.extend([period - 1, period, period + 1])

    deep_seasonal = seasonal and n_observations >= 4 * period
    if deep_seasonal:
        lags.append(2 * period)

    reach = max(2, n_observations // 4)
    windows = {3, 6, 12, period} if seasonal else {3, 6, 12}
    rolling_windows = sorted(w for w in windows if 2 <= w <= reach)
    if not rolling_windows:
        rolling_windows = [max(2, min(3, n_observations // 3))]

    lags = sorted({lag for lag in lags if 1 <= lag < n_observations}) or [1]

    return FeatureSpec(
        lags=lags,
        rolling_windows=rolling_windows,
        use_seasonal=deep_seasonal,
        seasonal_period=period,
        drivers=drivers or DriverPanel(),
    )


def _calendar_features(periods: list[date], frequency: ForecastFrequency) -> dict[str, FloatArray]:
    months = np.array([p.month for p in periods], dtype=float)

    out: dict[str, FloatArray] = {
        "month_sin": np.sin(2 * np.pi * months / 12.0),
        "month_cos": np.cos(2 * np.pi * months / 12.0),
        "quarter": np.array([(p.month - 1) // 3 + 1 for p in periods], dtype=float),
    }

    if frequency in (ForecastFrequency.DAILY, ForecastFrequency.WEEKLY):
        weekdays = np.array([p.weekday() for p in periods], dtype=float)
        weeks = np.array([p.isocalendar().week for p in periods], dtype=float)
        out["weekday_sin"] = np.sin(2 * np.pi * weekdays / 7.0)
        out["weekday_cos"] = np.cos(2 * np.pi * weekdays / 7.0)
        out["week_of_year_sin"] = np.sin(2 * np.pi * weeks / 52.0)
        out["week_of_year_cos"] = np.cos(2 * np.pi * weeks / 52.0)

    if frequency is ForecastFrequency.DAILY:
        out["day_of_month"] = np.array([p.day for p in periods], dtype=float)
        out["is_weekend"] = np.array([1.0 if p.weekday() >= 5 else 0.0 for p in periods])

    return out


def _rolling(lag1: FloatArray, window: int) -> tuple[FloatArray, FloatArray]:
    """Mean and population standard deviation over each full trailing window.

    A window holding any hole yields NaN, which is what NaN arithmetic does on
    its own — so this needs no mask and no Python loop. It is worth the stride
    trick: a recursive forecast rebuilds these columns once per step, and a
    hyperparameter search does that for every candidate on every split.
    """
    n = lag1.size
    means = np.full(n, np.nan)
    stds = np.full(n, np.nan)
    if n <= window:
        return means, stds

    view = np.lib.stride_tricks.sliding_window_view(lag1, window)
    with np.errstate(invalid="ignore"):
        means[window:] = view[1:].mean(axis=1)
        stds[window:] = view[1:].std(axis=1)
    return means, stds


def _feature_columns(
    values: FloatArray,
    periods: list[date],
    spec: FeatureSpec,
    frequency: ForecastFrequency,
) -> dict[str, FloatArray]:
    n = len(values)
    columns: dict[str, FloatArray] = {}

    for lag in spec.lags:
        shifted = np.full(n, np.nan)
        shifted[lag:] = values[:-lag]
        columns[f"lag_{lag}"] = shifted

    lag1 = np.full(n, np.nan)
    lag1[1:] = values[:-1]

    for window in spec.rolling_windows:
        means, stds = _rolling(lag1, window)
        columns[f"roll_mean_{window}"] = means
        columns[f"roll_std_{window}"] = stds
        columns[f"roll_delta_{window}"] = lag1 - means

    if spec.use_trend:
        columns["trend"] = np.arange(n, dtype=float)

    if spec.use_calendar:
        columns.update(_calendar_features(periods, frequency))

    if spec.use_seasonal and 2 * spec.seasonal_period < n:
        p = spec.seasonal_period
        seasonal_delta = np.full(n, np.nan)
        seasonal_delta[2 * p :] = values[p : n - p] - values[: n - 2 * p]
        columns["seasonal_delta"] = seasonal_delta

    columns.update(spec.drivers.columns(n))

    return columns


def _stack(columns: dict[str, FloatArray], n: int) -> tuple[FloatArray, list[str]]:
    names = sorted(columns)
    if not names:
        return np.empty((n, 0)), []
    return np.column_stack([columns[name] for name in names]), names


def build_design_matrix(
    values: FloatArray,
    periods: list[date],
    spec: FeatureSpec,
    frequency: ForecastFrequency,
) -> tuple[FloatArray, FloatArray, list[str], list[int]]:
    columns = _feature_columns(values, periods, spec, frequency)
    matrix, names = _stack(columns, len(values))

    complete = ~np.isnan(matrix).any(axis=1) & ~np.isnan(values)
    spec.names = names
    return matrix[complete], values[complete], names, np.flatnonzero(complete).tolist()


def build_future_row(
    history: FloatArray,
    history_periods: list[date],
    next_period: date,
    spec: FeatureSpec,
    frequency: ForecastFrequency,
) -> FloatArray:
    extended_values = np.concatenate([history, [np.nan]])
    extended_periods = [*history_periods, next_period]

    columns = _feature_columns(extended_values, extended_periods, spec, frequency)
    names = spec.names or sorted(columns)
    row = np.array([columns[name][-1] for name in names], dtype=float)

    if np.isnan(row).any():
        finite_history = history[np.isfinite(history)]
        filler = float(finite_history[-1]) if finite_history.size else 0.0
        row = np.where(np.isnan(row), filler, row)
    return row
