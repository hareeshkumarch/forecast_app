from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import numpy as np
import numpy.typing as npt

from app.forecasting.diagnostics import SeriesProfile, profile_series
from app.forecasting.features import FeatureSpec, build_design_matrix, build_future_row
from app.models.enums import ForecastFrequency, ModelKind

FloatArray = npt.NDArray[np.float64]

RANDOM_STATE = 20260804

MAX_STATE_SPACE_PERIOD = 24
MAX_FOURIER_HARMONICS = 3


class Forecaster(Protocol):
    kind: ModelKind

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
        steps = np.arange(1, horizon + 1, dtype=float)
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

        self._season = np.asarray(y[-period:], dtype=float)
        self._drift = 0.0

        if self.profile is not None and self.profile.has_trend and y.size >= 2 * period:
            previous = float(np.mean(y[-2 * period : -period]))
            current = float(np.mean(y[-period:]))
            self._drift = (current - previous) / period

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        period = len(self._season)
        base = np.array([self._season[i % period] for i in range(horizon)], dtype=float)
        return base + self._drift * np.arange(1, horizon + 1, dtype=float)

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
    _fitted: object | None = field(default=None, init=False)
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

                forecast = np.asarray(fitted.forecast(1), dtype=float)
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
        return np.asarray(self._fitted.forecast(horizon), dtype=float)

    @property
    def params(self) -> dict[str, object]:
        return dict(self._config)

    @property
    def min_observations(self) -> int:
        return 5


@dataclass
class ThetaForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    kind: ModelKind = field(default=ModelKind.THETA, init=False)
    _fitted: object | None = field(default=None, init=False)
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
                np.asarray(y, dtype=float),
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
        return np.asarray(self._fitted.forecast(horizon), dtype=float)

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
        occurrences = np.flatnonzero(np.asarray(y, dtype=float) > 0)
        if occurrences.size < 2:
            raise ValueError("Croston needs at least two non-zero demands.")

        sizes = np.asarray(y, dtype=float)[occurrences]
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
        return np.full(horizon, self._rate, dtype=float)

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
    kind: ModelKind = field(default=ModelKind.SARIMAX, init=False)
    _fitted: object | None = field(default=None, init=False)
    _config: dict[str, object] = field(default_factory=dict, init=False)
    _harmonics: int = field(default=0, init=False)
    _period: int = field(default=1, init=False)
    _train_size: int = field(default=0, init=False)

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

    def _exog(self, size: int, offset: int = 0) -> FloatArray | None:
        if self._harmonics <= 0:
            return None
        index = np.arange(offset, offset + size, dtype=float)
        return _fourier_terms(index, self._period, self._harmonics)

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
        exog = self._exog(y.size)

        best_fit = None
        best_order: tuple[int, int, int] | None = None
        best_score = float("inf")
        errors: list[str] = []

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
            except Exception as exc:
                errors.append(f"{order}: {type(exc).__name__}")
                continue

        if best_fit is None or best_order is None:
            raise ValueError(
                f"No SARIMAX order converged ({'; '.join(errors) if errors else 'no candidates'})."
            )

        self._fitted = best_fit
        self._config = {
            "order": list(best_order),
            "seasonal_order": list(seasonal_order),
            "fourier_harmonics": self._harmonics,
            "aicc": round(best_score, 3),
        }

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        if self._fitted is None:
            raise RuntimeError("fit() must be called before predict().")
        exog = self._exog(horizon, offset=self._train_size)
        return np.asarray(self._fitted.forecast(steps=horizon, exog=exog), dtype=float)

    @property
    def params(self) -> dict[str, object]:
        return dict(self._config)

    @property
    def min_observations(self) -> int:
        return 10


@dataclass
class GradientBoostingForecaster:
    frequency: ForecastFrequency
    profile: SeriesProfile | None = None
    max_depth: int | None = None
    learning_rate: float | None = None
    kind: ModelKind = field(default=ModelKind.GRADIENT_BOOSTING, init=False)
    _model: object | None = field(default=None, init=False)
    _spec: FeatureSpec | None = field(default=None, init=False)
    _history: FloatArray = field(default_factory=lambda: np.array([]), init=False)
    _periods: list[date] = field(default_factory=list, init=False)
    _hyper: dict[str, object] = field(default_factory=dict, init=False)

    def _hyperparameters(self, n_rows: int) -> dict[str, object]:
        depth = self.max_depth or int(np.clip(2 + n_rows // 60, 2, 6))
        rate = self.learning_rate or float(np.clip(0.30 / np.sqrt(max(n_rows, 1)), 0.02, 0.15))
        iterations = int(np.clip(n_rows * 6, 120, 600))
        leaf = max(2, min(20, n_rows // 12))

        noisy = self.profile is not None and self.profile.coefficient_of_variation > 0.5
        regularisation = 2.0 if noisy else 1.0

        return {
            "max_depth": depth,
            "learning_rate": round(rate, 4),
            "max_iter": iterations,
            "min_samples_leaf": leaf,
            "l2_regularization": regularisation,
            "early_stopping": n_rows >= 60,
        }

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        from sklearn.ensemble import HistGradientBoostingRegressor

        from app.forecasting.features import build_feature_spec

        spec = build_feature_spec(len(y), self.frequency, profile=self.profile)
        matrix, target, _names, _rows = build_design_matrix(y, periods, spec, self.frequency)

        if matrix.shape[0] < 8:
            raise ValueError(
                f"Only {matrix.shape[0]} usable training rows after lag construction; "
                "gradient boosting needs at least 8."
            )

        hyper = self._hyperparameters(matrix.shape[0])
        model = HistGradientBoostingRegressor(
            max_depth=int(hyper["max_depth"]),
            max_iter=int(hyper["max_iter"]),
            learning_rate=float(hyper["learning_rate"]),
            min_samples_leaf=int(hyper["min_samples_leaf"]),
            l2_regularization=float(hyper["l2_regularization"]),
            early_stopping=bool(hyper["early_stopping"]),
            validation_fraction=0.15 if hyper["early_stopping"] else None,
            random_state=RANDOM_STATE,
        )
        model.fit(matrix, target)

        self._model = model
        self._spec = spec
        self._hyper = hyper
        self._history = np.asarray(y, dtype=float).copy()
        self._periods = list(periods)

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        if self._model is None or self._spec is None:
            raise RuntimeError("fit() must be called before predict().")

        history = self._history.copy()
        periods = list(self._periods)
        predictions: list[float] = []

        for step in range(horizon):
            next_period = future_periods[step]
            row = build_future_row(history, periods, next_period, self._spec, self.frequency)
            value = float(self._model.predict(row.reshape(1, -1))[0])
            predictions.append(value)
            history = np.append(history, value)
            periods.append(next_period)

        return np.array(predictions, dtype=float)

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
        period = self.profile.seasonal_period if self.profile else _default_period(self.frequency)
        return max(12, min(period, 12) + 4)


def _default_period(frequency: ForecastFrequency) -> int:
    from app.forecasting.frequency import seasonal_period

    return seasonal_period(frequency)


def build_candidates(
    frequency: ForecastFrequency,
    options: dict[str, object] | None = None,
    profile: SeriesProfile | None = None,
) -> list[Forecaster]:
    opts = options or {}
    sarimax_order = opts.get("sarimax_order")
    gbm_depth = opts.get("gbm_max_depth")
    gbm_lr = opts.get("gbm_learning_rate")

    order_tuple = (
        tuple(sarimax_order)
        if isinstance(sarimax_order, (list, tuple)) and len(sarimax_order) == 3
        else None
    )

    candidates: list[Forecaster] = [
        NaiveForecaster(frequency, profile),
        SeasonalNaiveForecaster(frequency, profile),
        HoltWintersForecaster(frequency, profile),
        ThetaForecaster(frequency, profile),
        SarimaxForecaster(frequency, profile, order=order_tuple),  # type: ignore[arg-type]
        GradientBoostingForecaster(
            frequency,
            profile,
            max_depth=int(gbm_depth) if gbm_depth is not None else None,
            learning_rate=float(gbm_lr) if gbm_lr is not None else None,
        ),
    ]

    if profile is None or profile.intermittent:
        candidates.append(CrostonForecaster(frequency, profile))

    return candidates


def build_candidate(
    kind: ModelKind,
    frequency: ForecastFrequency,
    options: dict[str, object] | None = None,
    profile: SeriesProfile | None = None,
) -> Forecaster:
    for candidate in build_candidates(frequency, options, profile):
        if candidate.kind == kind:
            return candidate
    raise ValueError(f"Unknown candidate kind: {kind}")


def candidate_for_window(
    kind: ModelKind,
    frequency: ForecastFrequency,
    y: FloatArray,
    options: dict[str, object] | None = None,
) -> Forecaster:
    return build_candidate(kind, frequency, options, profile_series(y, frequency))
