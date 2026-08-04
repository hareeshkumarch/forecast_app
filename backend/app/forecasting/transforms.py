from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt

from app.forecasting.diagnostics import SeriesProfile
from app.forecasting.models import Forecaster
from app.models.enums import ModelKind

FloatArray = npt.NDArray[np.float64]


@dataclass(slots=True)
class Transform:
    kind: str
    shift: float = 0.0
    residual_variance: float = 0.0

    @property
    def active(self) -> bool:
        return self.kind == "log"

    def forward(self, values: FloatArray) -> FloatArray:
        array = np.asarray(values, dtype=float)
        if not self.active:
            return array.copy()
        return np.log(np.maximum(array + self.shift, 1e-9))

    def inverse(self, values: FloatArray) -> FloatArray:
        array = np.asarray(values, dtype=float)
        if not self.active:
            return array.copy()

        correction = self.residual_variance / 2.0 if self.residual_variance > 0 else 0.0
        return np.exp(np.clip(array + correction, -700.0, 700.0)) - self.shift


@dataclass(slots=True)
class TransformedForecaster:
    inner: Forecaster
    transform: Transform

    @property
    def kind(self) -> ModelKind:
        return self.inner.kind

    def fit(self, y: FloatArray, periods: list[date]) -> None:
        self.inner.fit(self.transform.forward(y), periods)

    def predict(self, horizon: int, future_periods: list[date]) -> FloatArray:
        return self.transform.inverse(self.inner.predict(horizon, future_periods))

    @property
    def params(self) -> dict[str, object]:
        return {**self.inner.params, "transform": self.transform.kind}

    @property
    def min_observations(self) -> int:
        return self.inner.min_observations

    def fitted_values(self) -> FloatArray | None:
        raw = getattr(getattr(self.inner, "_fitted", None), "fittedvalues", None)
        if raw is None:
            return None
        return self.transform.inverse(np.asarray(raw, dtype=float).ravel())


def build_transform(values: FloatArray, profile: SeriesProfile) -> Transform:
    if profile.transform != "log":
        return Transform(kind="none")

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return Transform(kind="none")

    minimum = float(np.min(finite))
    shift = 0.0 if minimum > 0 else abs(minimum) + 1.0

    transformed = np.log(np.maximum(finite + shift, 1e-9))
    variance = float(np.var(np.diff(transformed), ddof=1)) if transformed.size > 2 else 0.0

    return Transform(kind="log", shift=shift, residual_variance=min(variance, 1.0))
