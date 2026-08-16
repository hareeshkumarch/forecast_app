from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from app.core.config import settings

# `availability` is imported as a module and called through, not imported by
# name: the probe is the seam tests fake a deployment through, and a by-value
# import would bind past the patch.
from app.forecasting import availability
from app.forecasting.availability import ModelAvailability
from app.forecasting.diagnostics import SeriesProfile
from app.forecasting.drivers import DriverPanel
from app.forecasting.features import FeatureSpec, build_design_matrix, build_future_row
from app.forecasting.routing import route
from app.forecasting.tuning import (
    MIN_VALIDATION_ROWS,
    SearchSpace,
    as_float,
    as_int,
    blended_error,
    tune,
    validation_splits,
)
from app.models.enums import ForecastFrequency, ModelKind

FloatArray = npt.NDArray[np.float64]

FittedModel = Any

RANDOM_STATE = 20260804

OBSERVATIONS_PER_PARAMETER = 3
#: Hold-out windows the Prophet prior search uses. Every evaluation compiles
#: and fits a Stan model, so this buys most of the variance reduction that a
#: full pass over the splits would, at a cost anybody will actually wait for.
PROPHET_TUNING_SPLITS = 2
MAX_STATE_SPACE_PERIOD = 24
MAX_FOURIER_HARMONICS = 3

_APPROX_DAYS: dict[ForecastFrequency, float] = {
    ForecastFrequency.DAILY: 1.0,
    ForecastFrequency.WEEKLY: 7.0,
    ForecastFrequency.MONTHLY: 30.44,
    ForecastFrequency.QUARTERLY: 91.31,
}


class Forecaster(Protocol):
    @property
    def kind(self) -> ModelKind: ...

    def fit(self, y: FloatArray, periods: list[date]) -> None: ...

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray: ...

    @property
    def params(self) -> dict[str, object]: ...

    @property
    def min_observations(self) -> int: ...


def _aicc(log_likelihood: float, n_params: int, n_observations: int) -> float:
    if not np.isfinite(log_likelihood) or n_observations <= n_params + 1:
        return float("inf")
    aic = -2.0 * log_likelihood + 2.0 * n_params
    return aic + (2.0 * n_params * (n_params + 1)) / (n_observations - n_params - 1)


def _fourier_terms(index: FloatArray, period: int, harmonics: int) -> FloatArray:
    columns = []
    for order in range(1, harmonics + 1):
        angle = 2.0 * np.pi * order * index / period
        columns.append(np.sin(angle))
        columns.append(np.cos(angle))
    return np.column_stack(columns) if columns else np.empty((index.size, 0))


@dataclass
class NaiveForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    kind: ModelKind = field(default=ModelKind.NAIVE, init=False)
    _last: float = field(default=0.0, init=False)
    _drift: float = field(default=0.0, init=False)

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        finite = y[np.isfinite(y)]
        if finite.size == 0:
            raise ValueError("Naive forecast requires at least one finite observation.")

        self._last = float(finite[-1])
        self._drift = 0.0

        if self.profile is not None and self.profile.has_trend and finite.size >= 4:
            self._drift = float((finite[-1] - finite[0]) / (finite.size - 1))

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        steps = np.arange(1, horizon + 1, dtype=np.float64)
        return self._last + self._drift * steps

    @property
    def params(self) -> dict[str, object]:
        return {"last_value": self._last, "drift": self._drift}

    @property
    def min_observations(self) -> int:
        return 1


@dataclass
class SeasonalNaiveForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    kind: ModelKind = field(default=ModelKind.SEASONAL_NAIVE, init=False)
    _season: FloatArray = field(default_factory=lambda: np.array([]), init=False)
    _drift: float = field(default=0.0, init=False)

    def _period(self, n_observations: int) -> int:
        if self.profile is not None and self.profile.seasonal_period > 1:
            return self.profile.seasonal_period
        return max(1, min(n_observations, _default_period(self.frequency)))

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        period = self._period(y.size)
        if y.size < period:
            raise ValueError(f"Seasonal naive needs at least {period} observations.")

        self._season = np.asarray(y[-period:], dtype=np.float64)
        self._drift = 0.0

        if self.profile is not None and self.profile.has_trend and y.size >= 2 * period:
            previous = float(np.mean(y[-2 * period : -period]))
            current = float(np.mean(y[-period:]))
            self._drift = (current - previous) / period

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        period = len(self._season)
        base = np.array([self._season[i % period] for i in range(horizon)], dtype=np.float64)
        return base + self._drift * np.arange(1, horizon + 1, dtype=np.float64)

    @property
    def params(self) -> dict[str, object]:
        return {"seasonal_period": len(self._season), "drift": self._drift}

    @property
    def min_observations(self) -> int:
        if self.profile is not None and self.profile.seasonal_period > 1:
            return self.profile.seasonal_period
        return _default_period(self.frequency)


@dataclass
class HoltWintersForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    kind: ModelKind = field(default=ModelKind.HOLT_WINTERS, init=False)
    _fitted: FittedModel = field(default=None, init=False)
    _config: dict[str, object] = field(default_factory=dict, init=False)

    def _configurations(self, y: FloatArray) -> list[dict[str, object]]:
        period = self.profile.seasonal_period if self.profile else _default_period(self.frequency)
        seasonal_usable = period >= 2 and y.size >= 2 * period + 1
        seasonal_likely = seasonal_usable and (self.profile is None or self.profile.has_seasonality)

        seasonal_kinds: list[str | None] = [None]
        if seasonal_likely:
            seasonal_kinds.insert(0, "add")
            if bool(np.all(y > 0)):
                seasonal_kinds.insert(1, "mul")

        trends: list[tuple[str | None, bool]] = [("add", True), ("add", False), (None, False)]
        if self.profile is not None and not self.profile.has_trend:
            trends = [(None, False), ("add", True)]

        configurations: list[dict[str, object]] = []
        for seasonal in seasonal_kinds:
            for trend, damped in trends:
                configurations.append(
                    {
                        "trend": trend,
                        "damped_trend": damped if trend else False,
                        "seasonal": seasonal,
                        "seasonal_periods": period if seasonal else None,
                    }
                )
        return configurations

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        best_fit = None
        best_config: dict[str, object] | None = None
        best_score = float("inf")
        errors: list[str] = []

        for config in self._configurations(y):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = ExponentialSmoothing(
                        y,
                        trend=config["trend"],
                        damped_trend=bool(config["damped_trend"]),
                        seasonal=config["seasonal"],
                        seasonal_periods=config["seasonal_periods"],
                        initialization_method="estimated",
                    )
                    fitted = model.fit(optimized=True)

                score = float(getattr(fitted, "aicc", np.nan))
                if not np.isfinite(score):
                    score = float(getattr(fitted, "aic", np.inf))

                forecast = np.asarray(fitted.forecast(1), dtype=np.float64)
                if not np.all(np.isfinite(forecast)):
                    continue

                if score < best_score:
                    best_fit, best_config, best_score = fitted, config, score
            except Exception as exc:
                errors.append(f"{config['trend']}/{config['seasonal']}: {type(exc).__name__}")
                continue

        if best_fit is None or best_config is None:
            raise ValueError(
                "No exponential-smoothing configuration converged "
                f"({'; '.join(errors) if errors else 'no candidates'})."
            )

        self._fitted = best_fit
        self._config = {**best_config, "aicc": round(best_score, 3)}

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        if self._fitted is None:
            raise RuntimeError("fit() must be called before predict().")
        return np.asarray(self._fitted.forecast(horizon), dtype=np.float64)

    @property
    def params(self) -> dict[str, object]:
        return dict(self._config)

    @property
    def min_observations(self) -> int:
        return 5


@dataclass
class AutoEtsForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    kind: ModelKind = field(default=ModelKind.ETS, init=False)
    _fitted: FittedModel = field(default=None, init=False)
    _config: dict[str, object] = field(default_factory=dict, init=False)

    def _taxonomy(self, y: FloatArray) -> list[tuple[str, str | None, str | None, bool]]:
        period = self.profile.seasonal_period if self.profile else _default_period(self.frequency)
        seasonal_usable = (
            period >= 2
            and y.size >= 2 * period + 1
            and (self.profile is None or self.profile.has_seasonality)
        )
        positive = bool(np.all(y > 0))

        errors = ["add", "mul"] if positive else ["add"]
        trends: list[str | None] = [None, "add"]
        seasons: list[str | None] = [None]
        if seasonal_usable:
            seasons.append("add")
            if positive:
                seasons.append("mul")

        space: list[tuple[str, str | None, str | None, bool]] = []
        for error in errors:
            for trend in trends:
                for season in seasons:
                    if season == "mul" and error == "add":
                        continue
                    for damped in (False, True):
                        if damped and trend is None:
                            continue
                        space.append((error, trend, season, damped))
        return space

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel

        period = self.profile.seasonal_period if self.profile else _default_period(self.frequency)

        best_fit = None
        best_spec: tuple[str, str | None, str | None, bool] | None = None
        best_score = float("inf")

        for error, trend, season, damped in self._taxonomy(y):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = ETSModel(
                        np.asarray(y, dtype=np.float64),
                        error=error,
                        trend=trend,
                        seasonal=season,
                        damped_trend=damped,
                        seasonal_periods=period if season else None,
                    )
                    fitted = model.fit(disp=False)

                score = float(getattr(fitted, "aicc", np.nan))
                if not np.isfinite(score):
                    score = float(getattr(fitted, "aic", np.inf))
                if not np.isfinite(score):
                    continue

                if score < best_score:
                    best_fit, best_spec, best_score = fitted, (error, trend, season, damped), score
            except Exception:
                continue

        if best_fit is None or best_spec is None:
            raise ValueError("No ETS specification converged on this history.")

        error, trend, season, damped = best_spec
        self._fitted = best_fit
        self._config = {
            "error": error,
            "trend": trend,
            "seasonal": season,
            "damped_trend": damped,
            "seasonal_periods": period if season else None,
            "aicc": round(best_score, 3),
        }

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        if self._fitted is None:
            raise RuntimeError("fit() must be called before predict().")
        return np.asarray(self._fitted.forecast(horizon), dtype=np.float64)

    @property
    def params(self) -> dict[str, object]:
        return dict(self._config)

    @property
    def min_observations(self) -> int:
        seasonal = self.profile is not None and self.profile.has_seasonality
        period = self.profile.seasonal_period if self.profile else 0
        parameters = 5 + (period if seasonal else 0)

        return max(10, OBSERVATIONS_PER_PARAMETER * parameters)


@dataclass
class ProphetForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    changepoint_prior_scale: float | None = None
    interval_width: float = 0.8
    #: The metrics the run scores by, so the prior search minimises the same
    #: thing model selection will.
    metric_weights: dict[str, float] | None = None
    kind: ModelKind = field(default=ModelKind.PROPHET, init=False)
    _fitted: FittedModel = field(default=None, init=False)
    _config: dict[str, object] = field(default_factory=dict, init=False)

    @staticmethod
    def available() -> bool:
        # Not `find_spec("prophet")`. A Prophet whose Stan backend will not
        # load imports cleanly and only fails at fit, so an import check puts
        # it on the roster and then loses every backtest to an exception.
        return availability.prophet_availability().available

    def _seasonality_flags(self, y: FloatArray) -> dict[str, bool]:
        period = self.profile.seasonal_period if self.profile else 0
        seasonal = self.profile.has_seasonality if self.profile else False
        span_days = y.size * _APPROX_DAYS[self.frequency]

        return {
            "yearly_seasonality": seasonal and span_days >= 2 * 365,
            "weekly_seasonality": (
                seasonal and self.frequency is ForecastFrequency.DAILY and period in (7, 14)
            ),
            "daily_seasonality": False,
        }

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        status = availability.prophet_availability()
        if not status.available:
            raise ValueError(status.reason)

        import logging

        import pandas as pd
        from prophet import Prophet

        logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
        logging.getLogger("prophet").setLevel(logging.ERROR)

        flags = self._seasonality_flags(y)
        multiplicative = (
            self.profile is not None and self.profile.transform == "log" and bool(np.all(y > 0))
        )

        frame = pd.DataFrame({"ds": pd.to_datetime(periods), "y": np.asarray(y, dtype=np.float64)})
        mode = "multiplicative" if multiplicative else "additive"

        priors, search = self._priors(frame, mode, flags)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = Prophet(
                seasonality_mode=mode,
                interval_width=self.interval_width,
                **priors,
                **flags,
            )
            model.fit(frame)

        self._fitted = model
        self._config = {
            "seasonality_mode": mode,
            "interval_width": self.interval_width,
            **{key: float(value) for key, value in priors.items()},
            **{key: bool(value) for key, value in flags.items()},
            **search,
        }

    CHANGEPOINT_PRIORS = (0.01, 0.05, 0.25)
    SEASONALITY_PRIORS = (1.0, 10.0)

    def _priors(
        self, frame: object, mode: str, flags: dict[str, bool]
    ) -> tuple[dict[str, float], dict[str, object]]:
        default = {"changepoint_prior_scale": 0.05, "seasonality_prior_scale": 10.0}

        if self.changepoint_prior_scale is not None:
            return (
                {**default, "changepoint_prior_scale": self.changepoint_prior_scale},
                {"tuning_method": "set_by_the_run", "tuning_evaluations": 0},
            )

        import pandas as pd
        from prophet import Prophet

        rows = len(frame)  # type: ignore[arg-type]
        splits = validation_splits(rows, min(12, max(1, rows // 5)))
        if not splits:
            return default, {"tuning_method": "defaults_short_history", "tuning_evaluations": 0}

        # More than one window. A single hold-out picks the prior that suited
        # one stretch of history, and a changepoint prior in particular is
        # exactly the setting a single window cannot separate — whichever
        # value happens to bend towards that window's last turn wins. Capped
        # at two, because every evaluation here is a Stan fit.
        used_splits = splits[-PROPHET_TUNING_SPLITS:]
        windows = [
            (
                frame.iloc[:start],  # type: ignore[attr-defined]
                frame.iloc[start:end],  # type: ignore[attr-defined]
            )
            for start, end in used_splits
        ]

        best, best_score, evaluated = default, float("inf"), 0
        for changepoint in self.CHANGEPOINT_PRIORS:
            for seasonality in self.SEASONALITY_PRIORS:
                candidate = {
                    "changepoint_prior_scale": changepoint,
                    "seasonality_prior_scale": seasonality,
                }
                errors: list[float] = []
                for train, holdout in windows:
                    actual = np.asarray(holdout["y"].to_numpy(), dtype=np.float64)
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            trial = Prophet(
                                seasonality_mode=mode, interval_width=0.8, **candidate, **flags
                            )
                            trial.fit(train)
                            predicted = trial.predict(pd.DataFrame({"ds": holdout["ds"]}))
                    except Exception:
                        errors = []
                        break

                    yhat = np.asarray(predicted["yhat"].to_numpy(), dtype=np.float64)
                    if yhat.size != actual.size or not np.all(np.isfinite(yhat)):
                        errors = []
                        break
                    errors.append(blended_error(actual, yhat, self.metric_weights))

                if not errors:
                    continue

                evaluated += 1
                score = float(np.mean(errors))
                if score < best_score:
                    best, best_score = candidate, score

        if evaluated == 0:
            return default, {"tuning_method": "defaults_all_failed", "tuning_evaluations": 0}

        return best, {
            "tuning_method": "grid",
            "tuning_evaluations": evaluated,
            "tuning_folds": len(windows),
            "tuning_score": round(best_score, 6),
        }

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        if self._fitted is None:
            raise RuntimeError("fit() must be called before predict().")

        import pandas as pd

        frame = pd.DataFrame({"ds": pd.to_datetime(future_periods)})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            forecast = self._fitted.predict(frame)
        return np.asarray(forecast["yhat"].to_numpy(), dtype=np.float64)

    @property
    def params(self) -> dict[str, object]:
        return dict(self._config)

    @property
    def min_observations(self) -> int:
        return 12


@dataclass
class ThetaForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    kind: ModelKind = field(default=ModelKind.THETA, init=False)
    _fitted: FittedModel = field(default=None, init=False)
    _config: dict[str, object] = field(default_factory=dict, init=False)

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        from statsmodels.tsa.forecasting.theta import ThetaModel

        period = self.profile.seasonal_period if self.profile else _default_period(self.frequency)
        seasonal = (
            period >= 2
            and y.size >= 2 * period + 1
            and (self.profile is None or self.profile.has_seasonality)
        )
        multiplicative = seasonal and bool(np.all(y > 0))

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ThetaModel(
                np.asarray(y, dtype=np.float64),
                period=period if seasonal else 1,
                deseasonalize=seasonal,
                method="mul" if multiplicative else "add",
                use_test=False,
            )
            self._fitted = model.fit()

        self._config = {
            "seasonal_period": period if seasonal else None,
            "deseasonalize": seasonal,
            "decomposition": "mul" if multiplicative else "add",
        }

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        if self._fitted is None:
            raise RuntimeError("fit() must be called before predict().")
        return np.asarray(self._fitted.forecast(horizon), dtype=np.float64)

    @property
    def params(self) -> dict[str, object]:
        return dict(self._config)

    @property
    def min_observations(self) -> int:
        return 6


@dataclass
class CrostonForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    kind: ModelKind = field(default=ModelKind.CROSTON, init=False)
    _rate: float = field(default=0.0, init=False)
    _config: dict[str, object] = field(default_factory=dict, init=False)

    @staticmethod
    def _smooth(series: FloatArray, alpha: float) -> float:
        level = float(series[0])
        for value in series[1:]:
            level = alpha * float(value) + (1.0 - alpha) * level
        return level

    @staticmethod
    def _one_step_error(sizes: FloatArray, intervals: FloatArray, alpha: float) -> float:
        size_level, interval_level = float(sizes[0]), float(intervals[0])
        squared = 0.0
        for index in range(1, sizes.size):
            predicted = size_level / max(interval_level, 1e-9)
            actual = float(sizes[index]) / max(float(intervals[index]), 1e-9)
            squared += (actual - predicted) ** 2
            size_level = alpha * float(sizes[index]) + (1.0 - alpha) * size_level
            interval_level = alpha * float(intervals[index]) + (1.0 - alpha) * interval_level
        return squared / max(sizes.size - 1, 1)

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        occurrences = np.flatnonzero(np.asarray(y, dtype=np.float64) > 0)
        if occurrences.size < 2:
            raise ValueError("Croston needs at least two non-zero demands.")

        sizes = np.asarray(y, dtype=np.float64)[occurrences]
        intervals = np.diff(np.concatenate([[-1], occurrences])).astype(float)

        best_alpha, best_error = 0.1, float("inf")
        for alpha in (0.05, 0.1, 0.15, 0.2, 0.3):
            error = self._one_step_error(sizes, intervals, alpha)
            if error < best_error:
                best_alpha, best_error = alpha, error

        size_level = self._smooth(sizes, best_alpha)
        interval_level = max(self._smooth(intervals, best_alpha), 1e-9)
        debias = 1.0 - best_alpha / 2.0

        self._rate = float(size_level / interval_level * debias)
        self._config = {
            "alpha": best_alpha,
            "variant": "sba",
            "mean_interval": round(interval_level, 3),
            "mean_size": round(size_level, 3),
        }

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        return np.full(horizon, self._rate, dtype=np.float64)

    @property
    def params(self) -> dict[str, object]:
        return dict(self._config)

    @property
    def min_observations(self) -> int:
        return 8


@dataclass
class SarimaxForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    order: tuple[int, int, int] | None = None
    drivers: DriverPanel = field(default_factory=DriverPanel)
    kind: ModelKind = field(default=ModelKind.SARIMAX, init=False)
    _fitted: FittedModel = field(default=None, init=False)
    _config: dict[str, object] = field(default_factory=dict, init=False)
    _harmonics: int = field(default=0, init=False)
    _period: int = field(default=1, init=False)
    _train_size: int = field(default=0, init=False)
    _uses_drivers: bool = field(default=False, init=False)

    def _search_space(self, y: FloatArray) -> list[tuple[int, int, int]]:
        if self.order is not None:
            return [self.order]

        d = self.profile.difference_order if self.profile else 1
        d = int(np.clip(d, 0, 2))

        if y.size < 24:
            return [(1, d, 0), (0, d, 1), (1, d, 1)]
        return [(1, d, 1), (0, d, 1), (1, d, 0), (2, d, 1), (1, d, 2), (2, d, 2)]

    def _seasonal_order(self, y: FloatArray) -> tuple[int, int, int, int]:
        if self.profile is None:
            return (0, 0, 0, 0)

        period = self.profile.seasonal_period
        if not self.profile.has_seasonality or period < 2 or period > MAX_STATE_SPACE_PERIOD:
            return (0, 0, 0, 0)
        if y.size < 2 * period + 8:
            return (0, 0, 0, 0)

        seasonal_d = self.profile.seasonal_difference_order
        return (1, seasonal_d, 1 if y.size >= 3 * period else 0, period)

    def _exog(self, size: int, offset: int = 0, *, with_drivers: bool = True) -> FloatArray | None:
        blocks: list[FloatArray] = []

        if self._harmonics > 0:
            index = np.arange(offset, offset + size, dtype=np.float64)
            blocks.append(_fourier_terms(index, self._period, self._harmonics))

        if with_drivers and self.drivers:
            lagged = self.drivers.columns(offset + size)
            names = sorted(lagged)
            if names:
                block = np.column_stack([lagged[name][offset : offset + size] for name in names])
                if np.isfinite(block).all():
                    blocks.append(block)

        if not blocks:
            return None
        return np.column_stack(blocks) if len(blocks) > 1 else blocks[0]

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        seasonal_order = self._seasonal_order(y)
        self._period = self.profile.seasonal_period if self.profile else 1
        self._train_size = int(y.size)

        long_season = (
            self.profile is not None
            and self.profile.has_seasonality
            and self.profile.seasonal_period > MAX_STATE_SPACE_PERIOD
            and y.size >= 2 * self.profile.seasonal_period
        )
        self._harmonics = (
            min(MAX_FOURIER_HARMONICS, max(1, self._period // 8)) if long_season else 0
        )
        driver_choices = [True, False] if self.drivers else [False]

        best_fit = None
        best_order: tuple[int, int, int] | None = None
        best_drivers = False
        best_score = float("inf")
        errors: list[str] = []

        for with_drivers in driver_choices:
            exog = self._exog(y.size, with_drivers=with_drivers)
            for order in self._search_space(y):
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        model = SARIMAX(
                            y,
                            exog=exog,
                            order=order,
                            seasonal_order=seasonal_order,
                            enforce_stationarity=False,
                            enforce_invertibility=False,
                            trend="n",
                        )
                        fitted = model.fit(disp=False, maxiter=200)

                    score = float(getattr(fitted, "aicc", np.nan))
                    if not np.isfinite(score):
                        score = _aicc(float(fitted.llf), int(fitted.params.size), int(y.size))
                    if not np.isfinite(score):
                        continue

                    if score < best_score:
                        best_fit, best_order, best_score = fitted, order, score
                        best_drivers = with_drivers
                except Exception as exc:
                    errors.append(f"{order}: {type(exc).__name__}")
                    continue

        if best_fit is None or best_order is None:
            raise ValueError(
                f"No SARIMAX order converged ({'; '.join(errors) if errors else 'no candidates'})."
            )

        self._fitted = best_fit
        self._uses_drivers = best_drivers
        self._config = {
            "order": list(best_order),
            "seasonal_order": list(seasonal_order),
            "fourier_harmonics": self._harmonics,
            "aicc": round(best_score, 3),
            "drivers_offered": len(self.drivers.links),
            "drivers_used": (
                [f"{link.name} (lag {link.lag})" for link in self.drivers.links]
                if best_drivers
                else []
            ),
        }

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        if self._fitted is None:
            raise RuntimeError("fit() must be called before predict().")
        exog = self._exog(horizon, offset=self._train_size, with_drivers=self._uses_drivers)
        return np.asarray(self._fitted.forecast(steps=horizon, exog=exog), dtype=np.float64)

    @property
    def params(self) -> dict[str, object]:
        return dict(self._config)

    @property
    def min_observations(self) -> int:
        widest = (
            max(sum(order) for order in self._search_space(np.zeros(0)))
            if self.order is None
            else sum(self.order)
        )
        seasonal = self.profile is not None and self.profile.has_seasonality
        period = self.profile.seasonal_period if self.profile else 0
        parameters = widest + 1 + (2 if seasonal and period <= MAX_STATE_SPACE_PERIOD else 0)

        return max(10, OBSERVATIONS_PER_PARAMETER * parameters)


@dataclass
class GradientBoostingForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    max_depth: int | None = None
    learning_rate: float | None = None
    drivers: DriverPanel = field(default_factory=DriverPanel)
    #: The metrics the run scores by, so the hyperparameter search minimises
    #: the same thing model selection will.
    metric_weights: dict[str, float] | None = None
    kind: ModelKind = field(default=ModelKind.GRADIENT_BOOSTING, init=False)
    _model: FittedModel = field(default=None, init=False)
    _spec: FeatureSpec | None = field(default=None, init=False)
    _history: FloatArray = field(default_factory=lambda: np.array([]), init=False)
    _periods: list[date] = field(default_factory=list, init=False)
    _hyper: dict[str, object] = field(default_factory=dict, init=False)
    _keep: npt.NDArray[np.bool_] | None = field(default=None, init=False)

    def _search_space(self, n_rows: int) -> SearchSpace:
        depths = [2, 3, 4] if n_rows < 120 else [3, 4, 6, 8]
        rates = [0.03, 0.06, 0.1] if n_rows < 120 else [0.02, 0.05, 0.1, 0.15]
        leaves = sorted({2, max(2, n_rows // 40), max(3, n_rows // 20), max(4, n_rows // 10)})

        return SearchSpace(
            {
                "max_depth": depths,
                "learning_rate": rates,
                "min_samples_leaf": leaves,
                "l2_regularization": [0.0, 1.0, 5.0],
            }
        )

    def _estimator(self, params: dict[str, object], n_rows: int) -> FittedModel:
        from sklearn.ensemble import HistGradientBoostingRegressor

        early = n_rows >= 80
        return HistGradientBoostingRegressor(
            max_depth=as_int(params["max_depth"], 3),
            learning_rate=as_float(params["learning_rate"], 0.06),
            min_samples_leaf=as_int(params["min_samples_leaf"], 2),
            l2_regularization=as_float(params["l2_regularization"], 0.0),
            max_iter=int(np.clip(n_rows * 6, 120, 600)),
            early_stopping=early,
            validation_fraction=0.15 if early else None,
            random_state=RANDOM_STATE,
        )

    def _overrides(self) -> dict[str, object]:
        overrides: dict[str, object] = {}
        if self.max_depth is not None:
            overrides["max_depth"] = int(self.max_depth)
        if self.learning_rate is not None:
            overrides["learning_rate"] = float(self.learning_rate)
        return overrides

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        from app.forecasting.features import build_feature_spec, driver_mask

        spec = build_feature_spec(
            len(y), self.frequency, profile=self.profile, drivers=self.drivers
        )
        matrix, target, names, rows = build_design_matrix(y, periods, spec, self.frequency)

        min_rows = settings.min_gbm_rows
        if matrix.shape[0] < min_rows:
            raise ValueError(
                f"Only {matrix.shape[0]} usable training rows after lag construction; "
                f"gradient boosting needs at least {min_rows}."
            )

        n_rows = int(matrix.shape[0])
        space = self._search_space(n_rows)
        overrides = self._overrides()

        if overrides:
            space = SearchSpace(
                {
                    key: ([overrides[key]] if key in overrides else values)
                    for key, values in space.choices.items()
                }
            )

        from_driver = driver_mask(names)
        offered = bool(from_driver.any())
        if offered:
            space = SearchSpace({**space.choices, "drivers": [True, False]})

        def fit_predict(params: dict[str, object], start: int, end: int) -> FloatArray:
            """Score these parameters the way the model will really be asked.

            Reading the validation block out of the design matrix hands the
            model the true lag-1 value at every step — it is being graded on
            one-step-ahead accuracy with the answers in front of it. Used for
            real it feeds its own output back, so a candidate that leans hard
            on the last observation looks superb here and drifts badly there.
            The search then picks exactly the wrong depth and learning rate.
            """
            keep = self._kept_columns(params, from_driver)
            estimator = self._estimator(params, start)
            estimator.fit(matrix[:start][:, keep], target[:start])
            return self._recursive_predictions(estimator, keep, spec, y, periods, rows, start, end)

        horizon = self.profile.seasonal_period if self.profile else 6
        result = tune(
            "gradient_boosting",
            matrix,
            target,
            space,
            fit_predict,
            max(1, min(horizon, 12)),
            metric_weights=self.metric_weights,
        )

        keep = self._kept_columns(result.params, from_driver)
        model = self._estimator(result.params, n_rows)
        model.fit(matrix[:, keep], target)

        used = [
            name
            for name, kept in zip(names, keep, strict=True)
            if kept and name.startswith("driver_")
        ]

        self._model = model
        self._spec = spec
        self._keep = keep
        self._hyper = {
            **result.params,
            **result.as_dict(),
            "drivers_offered": len(self.drivers.links) if offered else 0,
            "drivers_used": used,
        }
        self._history = np.asarray(y, dtype=np.float64).copy()
        self._periods = list(periods)

    @staticmethod
    def _kept_columns(
        params: dict[str, object], from_driver: npt.NDArray[np.bool_]
    ) -> npt.NDArray[np.bool_]:
        if params.get("drivers", True):
            return np.ones(from_driver.size, dtype=bool)
        return ~from_driver

    def _recursive_predictions(
        self,
        estimator: FittedModel,
        keep: npt.NDArray[np.bool_],
        spec: FeatureSpec,
        y: FloatArray,
        periods: list[date],
        rows: list[int],
        start: int,
        end: int,
    ) -> FloatArray:
        """Walk the validation block forward, feeding each step its own output."""
        from app.forecasting.features import build_future_row

        first, last = rows[start], rows[end - 1]
        history = np.asarray(y[:first], dtype=np.float64).copy()
        seen = list(periods[:first])
        predicted: dict[int, float] = {}

        for position in range(first, last + 1):
            row = build_future_row(history, seen, periods[position], spec, self.frequency)
            value = float(estimator.predict(row[keep].reshape(1, -1))[0])
            predicted[position] = value
            history = np.append(history, value)
            seen.append(periods[position])

        return np.array([predicted[rows[index]] for index in range(start, end)], dtype=np.float64)

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        if self._model is None or self._spec is None:
            raise RuntimeError("fit() must be called before predict().")

        history = self._history.copy()
        periods = list(self._periods)
        predictions: list[float] = []

        keep = self._keep

        for step in range(horizon):
            next_period = future_periods[step]
            row = build_future_row(history, periods, next_period, self._spec, self.frequency)
            if keep is not None:
                row = row[keep]
            value = float(self._model.predict(row.reshape(1, -1))[0])
            predictions.append(value)
            history = np.append(history, value)
            periods.append(next_period)

        return np.array(predictions, dtype=np.float64)

    @property
    def params(self) -> dict[str, object]:
        if self._spec is None:
            return {}
        return {
            "lags": self._spec.lags,
            "rolling_windows": self._spec.rolling_windows,
            "seasonal_period": self._spec.seasonal_period,
            "n_features": len(self._spec.names),
            "random_state": RANDOM_STATE,
            **self._hyper,
        }

    @property
    def min_observations(self) -> int:
        seasonal = self.profile is not None and self.profile.has_seasonality
        period = self.profile.seasonal_period if self.profile else _default_period(self.frequency)
        deepest_lag = min(period, 12) + 1 if seasonal else 3

        return deepest_lag + 2 * MIN_VALIDATION_ROWS


@dataclass
class EnsembleForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    members: tuple[ModelKind, ...] = (
        ModelKind.THETA,
        ModelKind.ETS,
        ModelKind.SARIMAX,
    )
    weights: dict[ModelKind, float] | None = None
    kind: ModelKind = field(default=ModelKind.ENSEMBLE, init=False)
    _fitted: list[Forecaster] = field(default_factory=list, init=False)
    _config: dict[str, object] = field(default_factory=dict, init=False)

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        fitted: list[Forecaster] = []
        joined: list[str] = []
        skipped: list[str] = []

        for member in self.members:
            try:
                model = build_candidate(member, self.frequency, None, self.profile)
                if y.size < model.min_observations:
                    raise ValueError("not enough history")
                model.fit(y, periods)
                fitted.append(model)
                joined.append(member.value)
            except Exception as exc:
                skipped.append(f"{member.value} ({type(exc).__name__})")
                continue

        if len(fitted) < 2:
            raise ValueError(
                "A combination needs at least two members that fit; "
                f"only {len(fitted)} did ({', '.join(skipped) or 'none skipped'})."
            )

        self._fitted = fitted
        self._config = {
            "members": joined,
            "combiner": "weighted_mean" if self.weights else "median",
            "skipped": skipped,
        }
        if self.weights:
            self._config["weights"] = {
                kind.value: round(weight, 4) for kind, weight in self.weights.items()
            }

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        if not self._fitted:
            raise RuntimeError("fit() must be called before predict().")

        stacked: list[FloatArray] = []
        share: list[float] = []

        for model in self._fitted:
            prediction = np.asarray(
                model.predict(horizon, future_periods), dtype=np.float64
            ).ravel()
            if prediction.size == horizon and np.all(np.isfinite(prediction)):
                stacked.append(prediction)
                share.append((self.weights or {}).get(model.kind, 0.0))

        if not stacked:
            raise RuntimeError("No ensemble member produced a usable forecast.")

        if self.weights and sum(share) > 0.0:
            return np.average(np.vstack(stacked), axis=0, weights=share)

        return np.median(np.vstack(stacked), axis=0)

    @property
    def params(self) -> dict[str, object]:
        return dict(self._config)

    @property
    def min_observations(self) -> int:
        return 12


def _default_period(frequency: ForecastFrequency) -> int:
    from app.forecasting.frequency import seasonal_period

    return seasonal_period(frequency)


def _metric_weights(
    options: dict[str, object], profile: SeriesProfile | None
) -> dict[str, float] | None:
    """The run's scoring weights, or the ones its profile implies."""
    from app.forecasting.selection import metric_weights_for

    supplied = options.get("metric_weights")
    if isinstance(supplied, dict) and supplied:
        return {str(key): float(value) for key, value in supplied.items()}
    return metric_weights_for(bool(profile.intermittent)) if profile is not None else None


def build_candidates(
    frequency: ForecastFrequency,
    options: dict[str, object] | None = None,
    profile: SeriesProfile | None = None,
    drivers: DriverPanel | None = None,
) -> list[Forecaster]:
    opts = options or {}
    panel = drivers or DriverPanel()
    sarimax_order = opts.get("sarimax_order")
    gbm_depth = opts.get("gbm_max_depth")
    gbm_lr = opts.get("gbm_learning_rate")
    prophet_cps = opts.get("prophet_changepoint_prior_scale")
    prophet_iw = opts.get("prophet_interval_width")
    allowed_models = opts.get("candidate_models")

    order_tuple = (
        tuple(sarimax_order)
        if isinstance(sarimax_order, list | tuple) and len(sarimax_order) == 3
        else None
    )

    candidates: list[Forecaster] = [
        NaiveForecaster(frequency, profile),
        SeasonalNaiveForecaster(frequency, profile),
        HoltWintersForecaster(frequency, profile),
        AutoEtsForecaster(frequency, profile),
        ThetaForecaster(frequency, profile),
        SarimaxForecaster(frequency, profile, order=order_tuple, drivers=panel),  # type: ignore[arg-type]
        GradientBoostingForecaster(
            frequency,
            profile,
            max_depth=as_int(gbm_depth, 3) if gbm_depth is not None else None,
            learning_rate=as_float(gbm_lr, 0.06) if gbm_lr is not None else None,
            drivers=panel,
            metric_weights=_metric_weights(opts, profile),
        ),
    ]

    if ProphetForecaster.available():
        candidates.append(
            ProphetForecaster(
                frequency,
                profile,
                changepoint_prior_scale=(
                    as_float(prophet_cps, 0.05) if prophet_cps is not None else None
                ),
                interval_width=as_float(prophet_iw, 0.8) if prophet_iw is not None else 0.8,
                metric_weights=_metric_weights(opts, profile),
            )
        )

    if profile is None or profile.intermittent:
        candidates.append(CrostonForecaster(frequency, profile))

    # The demand class is a gate, not a hint. Offering Croston alongside the
    # smooth-demand models leaves the selector free to pick one of them on an
    # intermittent series whenever the zeros happen to line up over a fold,
    # which is the confident-nonsense case the classification exists to
    # prevent. Baselines survive every class — they are the floor.
    routing = route(profile)
    routed = [candidate for candidate in candidates if routing.permits(candidate.kind)]
    if routed:
        candidates = routed

    if isinstance(allowed_models, list) and allowed_models:
        allowed_set = {str(model).lower() for model in allowed_models}
        filtered = [c for c in candidates if c.kind.value.lower() in allowed_set]
        if not filtered:
            # Falling back to the full roster made restricting a run to models
            # this deployment cannot fit — Prophet without Prophet installed,
            # Croston on a series that is not intermittent — run everything
            # instead, and report the winner as though it had been asked for.
            #
            # Two very different reasons land here, and the message says which:
            # a model missing from the deployment is the operator's to fix,
            # while one ruled out for this series is the user's to reconsider.
            raise ValueError(_no_candidates_message(allowed_set, candidates))
        return filtered

    return candidates


#: Titles for error copy. The wire format stays `ModelKind`; this is only for
#: sentences a person reads.
MODEL_LABELS: dict[ModelKind, str] = {
    ModelKind.NAIVE: "Naive",
    ModelKind.SEASONAL_NAIVE: "Seasonal Naive",
    ModelKind.HOLT_WINTERS: "Holt-Winters",
    ModelKind.ETS: "Auto-ETS",
    ModelKind.THETA: "Theta",
    ModelKind.CROSTON: "Croston (Intermittent)",
    ModelKind.SARIMAX: "SARIMAX",
    ModelKind.PROPHET: "Prophet",
    ModelKind.GRADIENT_BOOSTING: "Gradient Boosting",
    ModelKind.ENSEMBLE: "Ensemble",
}


def label_for(kind: ModelKind | str) -> str:
    """`ModelKind.SEASONAL_NAIVE` -> "Seasonal Naive"; unknown values pass through."""
    try:
        return MODEL_LABELS[ModelKind(kind)]
    except ValueError:
        return str(kind).replace("_", " ").title()


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _no_candidates_message(allowed: set[str], offered: list[Forecaster]) -> str:
    """Why a model restriction left nothing to fit, in terms a user can act on."""
    unavailable = unavailable_models()
    asked_for_unavailable = sorted(
        label_for(kind) for kind in unavailable if kind.value.lower() in allowed
    )
    runnable = _join(sorted({label_for(c.kind) for c in offered}))

    if asked_for_unavailable and len(asked_for_unavailable) == len(allowed):
        # Everything they ticked is missing from the deployment, so pointing
        # at the series would be a red herring — nothing about their data is
        # the problem.
        return (
            f"{_join(asked_for_unavailable)} "
            f"{'is' if len(asked_for_unavailable) == 1 else 'are'} not available on this "
            f"server, so there is nothing to backtest. Choose another model — "
            f"{runnable} can be fitted here."
        )

    ruled_out = _join(sorted(label_for(name) for name in allowed))
    return (
        f"None of the models you chose ({ruled_out}) suit this series, so there is "
        f"nothing to backtest. For this series the platform can fit {runnable}."
    )


def unavailable_models() -> dict[ModelKind, ModelAvailability]:
    """Models this deployment cannot fit, keyed by kind.

    Returns the whole availability record rather than a string, because the
    two halves of it go to different places: `reason` is rendered next to the
    run's other candidates, and `operator_hint` is for logs and the health
    endpoint. Flattening them is what put `pip install` in the dashboard.
    """
    status = availability.prophet_availability()
    return {} if status.available else {ModelKind.PROPHET: status}


def build_candidate(
    kind: ModelKind,
    frequency: ForecastFrequency,
    options: dict[str, object] | None = None,
    profile: SeriesProfile | None = None,
    drivers: DriverPanel | None = None,
) -> Forecaster:
    for candidate in build_candidates(frequency, options, profile, drivers):
        if candidate.kind == kind:
            return candidate
    raise ValueError(f"Unknown candidate kind: {kind}")
