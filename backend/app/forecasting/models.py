
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import numpy as np
import numpy.typing as npt

from app.forecasting.features import FeatureSpec, build_design_matrix, build_future_row
from app.forecasting.frequency import seasonal_period
from app.models.enums import ForecastFrequency, ModelKind

FloatArray = npt.NDArray[np.float64]

RANDOM_STATE = 20260804


class Forecaster(Protocol):
    kind: ModelKind

    def fit(self, y: FloatArray, periods: list[date]) -> None: ...

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray: ...

    @property
    def params(self) -> dict[str, object]: ...

    @property
    def min_observations(self) -> int: ...


@dataclass
class NaiveForecaster:

    frequency: ForecastFrequency
    kind: ModelKind = field(default=ModelKind.NAIVE, init=False)
    _last: float = field(default=0.0, init=False)

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        finite = y[np.isfinite(y)]
        if finite.size == 0:
            raise ValueError("Naive forecast requires at least one finite observation.")
        self._last = float(finite[-1])

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        return np.full(horizon, self._last, dtype=float)

    @property
    def params(self) -> dict[str, object]:
        return {"last_value": self._last}

    @property
    def min_observations(self) -> int:
        return 1


@dataclass
class SeasonalNaiveForecaster:

    frequency: ForecastFrequency
    kind: ModelKind = field(default=ModelKind.SEASONAL_NAIVE, init=False)
    _season: FloatArray = field(default_factory=lambda: np.array([]), init=False)

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        period = seasonal_period(self.frequency)
        if y.size < period:
            raise ValueError(f"Seasonal naive needs at least {period} observations.")
        self._season = np.asarray(y[-period:], dtype=float)

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        period = len(self._season)
                                                       
        return np.array([self._season[i % period] for i in range(horizon)], dtype=float)

    @property
    def params(self) -> dict[str, object]:
        return {"seasonal_period": len(self._season)}

    @property
    def min_observations(self) -> int:
        return seasonal_period(self.frequency)


@dataclass
class HoltWintersForecaster:

    frequency: ForecastFrequency
    kind: ModelKind = field(default=ModelKind.HOLT_WINTERS, init=False)
    _fitted: object | None = field(default=None, init=False)
    _config: dict[str, object] = field(default_factory=dict, init=False)

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        period = seasonal_period(self.frequency)
                                                                       
                                                     
        use_seasonal = y.size >= 2 * period + 1

                                                                   
        seasonal_kind = "add"

        self._config = {
            "trend": "add",
            "damped_trend": True,
            "seasonal": seasonal_kind if use_seasonal else None,
            "seasonal_periods": period if use_seasonal else None,
        }

        with warnings.catch_warnings():
                                                                            
                                                                             
            warnings.simplefilter("ignore")
            model = ExponentialSmoothing(
                y,
                trend="add",
                damped_trend=True,
                seasonal=seasonal_kind if use_seasonal else None,
                seasonal_periods=period if use_seasonal else None,
                initialization_method="estimated",
            )
            self._fitted = model.fit(optimized=True)

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
class SarimaxForecaster:

    frequency: ForecastFrequency
    order: tuple[int, int, int] | None = None
    kind: ModelKind = field(default=ModelKind.SARIMAX, init=False)
    _fitted: object | None = field(default=None, init=False)
    _config: dict[str, object] = field(default_factory=dict, init=False)

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        from app.core.config import settings

        period = seasonal_period(self.frequency)
                                                                          
        use_seasonal = y.size >= 3 * period

        order = self.order or (
            settings.sarimax_order_p,
            settings.sarimax_order_d,
            settings.sarimax_order_q,
        )
        seasonal_order = (1, 1, 1, period) if use_seasonal else (0, 0, 0, 0)
        self._config = {"order": order, "seasonal_order": seasonal_order}

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = SARIMAX(
                y,
                order=order,
                seasonal_order=seasonal_order,
                enforce_stationarity=False,
                enforce_invertibility=False,
                trend="n",
            )
            self._fitted = model.fit(disp=False, maxiter=200)

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        if self._fitted is None:
            raise RuntimeError("fit() must be called before predict().")
        return np.asarray(self._fitted.forecast(steps=horizon), dtype=float)

    @property
    def params(self) -> dict[str, object]:
        return {k: list(v) if isinstance(v, tuple) else v for k, v in self._config.items()}

    @property
    def min_observations(self) -> int:
        return 10


@dataclass
class GradientBoostingForecaster:

    frequency: ForecastFrequency
    max_depth: int | None = None
    learning_rate: float | None = None
    kind: ModelKind = field(default=ModelKind.GRADIENT_BOOSTING, init=False)
    _model: object | None = field(default=None, init=False)
    _spec: FeatureSpec | None = field(default=None, init=False)
    _history: FloatArray = field(default_factory=lambda: np.array([]), init=False)
    _periods: list[date] = field(default_factory=list, init=False)

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        from sklearn.ensemble import HistGradientBoostingRegressor

        from app.core.config import settings
        from app.forecasting.features import build_feature_spec

        spec = build_feature_spec(len(y), self.frequency)
        matrix, target, _names, _rows = build_design_matrix(y, periods, spec, self.frequency)

        if matrix.shape[0] < 8:
            raise ValueError(
                f"Only {matrix.shape[0]} usable training rows after lag construction; "
                "gradient boosting needs at least 8."
            )

        depth = self.max_depth or settings.gbm_max_depth
        lr = self.learning_rate or settings.gbm_learning_rate

        model = HistGradientBoostingRegressor(
            max_depth=depth,
            max_iter=200,
            learning_rate=lr,
            min_samples_leaf=max(3, matrix.shape[0] // 12),
            l2_regularization=1.0,
            early_stopping=False,
            random_state=RANDOM_STATE,
        )
        model.fit(matrix, target)

        self._model = model
        self._spec = spec
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
        from app.core.config import settings
        return {
            "lags": self._spec.lags,
            "rolling_windows": self._spec.rolling_windows,
            "n_features": len(self._spec.names),
            "max_depth": self.max_depth or settings.gbm_max_depth,
            "max_iter": 200,
            "learning_rate": self.learning_rate or settings.gbm_learning_rate,
            "random_state": RANDOM_STATE,
        }

    @property
    def min_observations(self) -> int:
                                                              
        return max(12, seasonal_period(self.frequency) + 4)


def build_candidates(
    frequency: ForecastFrequency,
    options: dict[str, object] | None = None,
) -> list[Forecaster]:
    opts = options or {}
    sarimax_order = opts.get("sarimax_order")
    gbm_depth = opts.get("gbm_max_depth")
    gbm_lr = opts.get("gbm_learning_rate")

    order_tuple = (
        tuple(sarimax_order) if isinstance(sarimax_order, (list, tuple)) and len(sarimax_order) == 3 else None
    )

    return [
        NaiveForecaster(frequency),
        SeasonalNaiveForecaster(frequency),
        HoltWintersForecaster(frequency),
        SarimaxForecaster(frequency, order=order_tuple),  # type: ignore[arg-type]
        GradientBoostingForecaster(
            frequency,
            max_depth=int(gbm_depth) if gbm_depth is not None else None,
            learning_rate=float(gbm_lr) if gbm_lr is not None else None,
        ),
    ]


def build_candidate(
    kind: ModelKind,
    frequency: ForecastFrequency,
    options: dict[str, object] | None = None,
) -> Forecaster:
    candidates = build_candidates(frequency, options)
    for c in candidates:
        if c.kind == kind:
            return c
    raise ValueError(f"Unknown candidate kind: {kind}")
