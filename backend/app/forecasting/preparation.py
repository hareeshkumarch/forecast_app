from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from app.models.enums import GapFill

FloatArray = npt.NDArray[np.float64]

INTERMITTENT_ZERO_SHARE = 0.30
OUTLIER_SIGMAS = 3.5
MIN_WINSORISE_POINTS = 5


def resolve_fill(values: FloatArray, requested: GapFill) -> GapFill:
    if requested is not GapFill.AUTO:
        return requested

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return GapFill.ZERO

    zero_share = float(np.mean(np.isclose(finite, 0.0)))
    return GapFill.ZERO if zero_share >= INTERMITTENT_ZERO_SHARE else GapFill.INTERPOLATE


def fill_gaps(values: FloatArray, fill: GapFill) -> FloatArray:
    array = np.asarray(values, dtype=float).copy()
    holes = ~np.isfinite(array)
    if not np.any(holes):
        return array

    applied = resolve_fill(array, fill)
    if applied is GapFill.NONE:
        return array

    known = np.flatnonzero(~holes)
    if known.size == 0 or applied is GapFill.ZERO:
        array[holes] = 0.0
        return array

    array[holes] = np.interp(np.flatnonzero(holes), known, array[known])
    return array


def winsorise(values: FloatArray, sigmas: float = OUTLIER_SIGMAS) -> FloatArray:
    array = np.asarray(values, dtype=float)
    finite = array[np.isfinite(array)]
    if finite.size < MIN_WINSORISE_POINTS:
        return array.copy()

    centre = float(np.median(finite))
    deviation = float(np.median(np.abs(finite - centre)))
    if deviation <= 0:
        return array.copy()

    spread = 1.4826 * deviation * sigmas
    return np.clip(array, centre - spread, centre + spread)


@dataclass(slots=True, frozen=True)
class Preparation:
    fill: GapFill = GapFill.NONE
    winsorise_sigmas: float | None = None

    @property
    def is_identity(self) -> bool:
        return self.fill is GapFill.NONE and self.winsorise_sigmas is None

    def apply(self, window: FloatArray) -> FloatArray:
        array = np.asarray(window, dtype=float)
        if self.fill is not GapFill.NONE:
            array = fill_gaps(array, self.fill)
        if self.winsorise_sigmas is not None:
            array = winsorise(array, self.winsorise_sigmas)
        return np.asarray(array, dtype=float)
