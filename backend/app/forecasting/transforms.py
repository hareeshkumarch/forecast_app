from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt

from app.forecasting.diagnostics import SeriesProfile
from app.forecasting.models import Forecaster
from app.models.enums import ModelKind

FloatArray = npt.NDArray[np.float64]


POWER_LAMBDA_MARGIN = 0.05


@dataclass(slots=True)
class Transform:
    kind: str
    shift: float = 0.0
    residual_variance: float = 0.0
    lam: float = 1.0

    @property
    def active(self) -> bool:
        return self.kind in {"log", "power"}

    def forward(self, values: FloatArray) -> FloatArray:
        array = np.asarray(values, dtype=float)
        if not self.active:
            return array.copy()
        shifted = np.maximum(array + self.shift, 1e-9)
        if self.kind == "log":
            return np.log(shifted)
        return (np.power(shifted, self.lam) - 1.0) / self.lam

    def inverse(self, values: FloatArray) -> FloatArray:
        array = np.asarray(values, dtype=float)
        if not self.active:
            return array.copy()

        if self.kind == "log":
            correction = self.residual_variance / 2.0 if self.residual_variance > 0 else 0.0
            return np.exp(np.clip(array + correction, -700.0, 700.0)) - self.shift

        base = np.maximum(self.lam * array + 1.0, 1e-9)
        mean = np.power(base, 1.0 / self.lam)
        if self.residual_variance > 0.0:
            widen = 1.0 + self.residual_variance * (1.0 - self.lam) / (2.0 * np.square(base))
            mean = mean * np.clip(widen, 0.5, 2.0)
        return np.where(np.isfinite(mean), mean, 0.0) - self.shift


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


def _step_variance(transformed: FloatArray) -> float:
    if transformed.size <= 2:
        return 0.0
    variance = float(np.var(np.diff(transformed), ddof=1))
    return variance if np.isfinite(variance) else 0.0


def build_transform(values: FloatArray, profile: SeriesProfile) -> Transform:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return Transform(kind="none")

    minimum = float(np.min(finite))
    shift = 0.0 if minimum > 0 else abs(minimum) + 1.0

    if profile.transform == "log":
        transformed = np.log(np.maximum(finite + shift, 1e-9))
        return Transform(
            kind="log", shift=shift, residual_variance=min(_step_variance(transformed), 1.0)
        )

    lam = float(profile.box_cox_lambda)
    if profile.transform != "none" or not np.isfinite(lam):
        return Transform(kind="none")
    if abs(lam - 1.0) < POWER_LAMBDA_MARGIN or lam <= 0.0:
        return Transform(kind="none")

    transformed = (np.power(np.maximum(finite + shift, 1e-9), lam) - 1.0) / lam
    return Transform(
        kind="power", shift=shift, residual_variance=_step_variance(transformed), lam=lam
    )
