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
            return np.exp(np.clip(array, -700.0, 700.0)) - self.shift

        # Below `lam * z + 1 == 0` the transform has no inverse: the model is
        # predicting past the bottom of the scale it was fitted on. The floor
        # of that scale is the answer, and it is returned exactly rather than
        # as whatever a clamped power happens to evaluate to.
        raised = self.lam * array + 1.0
        inside = raised > 0.0
        base = np.where(inside, raised, 1.0)
        mean = np.power(base, 1.0 / self.lam)
        mean = np.where(inside & np.isfinite(mean), mean, 0.0)
        return mean - self.shift


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
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return Transform(kind="none")

    minimum = float(np.min(finite))
    shift = 0.0 if minimum > 0 else abs(minimum) + 1.0

    if profile.transform == "log":
        return Transform(kind="log", shift=shift)

    lam = float(profile.box_cox_lambda)
    if profile.transform != "none" or not np.isfinite(lam):
        return Transform(kind="none")
    if abs(lam - 1.0) < POWER_LAMBDA_MARGIN or lam <= 0.0:
        return Transform(kind="none")

    return Transform(kind="power", shift=shift, lam=lam)
