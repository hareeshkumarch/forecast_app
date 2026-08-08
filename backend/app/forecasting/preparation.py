"""Cleaning a series without telling it what happens next.

Two of the things done to a series before it is fitted depend on the values
around them: a missing period is interpolated from its neighbours, and an
outlier is clipped against the spread of the whole column. Do either one over
the full history and then backtest on the result, and every fold's training
data has been touched by the very observations it is about to be scored
against — the validation says the model is better than it is, and nothing
about the report shows why.

So the work is expressed as a `Preparation` rather than done up front. It is
applied to a window, and the backtest applies it to each fold's training slice
before fitting. The final refit sees the whole history, which is correct there,
because by then the whole history *is* the training data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from app.models.enums import GapFill

FloatArray = npt.NDArray[np.float64]

#: Above this share of zeros a series is intermittent, and a gap in it is far
#: more likely to be a period with no demand than a period nobody reported.
INTERMITTENT_ZERO_SHARE = 0.30
#: Robust deviations beyond which a value is clipped rather than believed.
OUTLIER_SIGMAS = 3.5
#: Below this many points the median and its deviation are not worth trusting.
MIN_WINSORISE_POINTS = 5


def resolve_fill(values: FloatArray, requested: GapFill) -> GapFill:
    """What AUTO means for this window.

    Resolved per window rather than once for the series: a fold can only decide
    from what it can see, and the alternative is a decision made with the
    validation data in hand.
    """
    if requested is not GapFill.AUTO:
        return requested

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return GapFill.ZERO

    zero_share = float(np.mean(np.isclose(finite, 0.0)))
    return GapFill.ZERO if zero_share >= INTERMITTENT_ZERO_SHARE else GapFill.INTERPOLATE


def fill_gaps(values: FloatArray, fill: GapFill) -> FloatArray:
    """Fill the holes in a window from that window alone.

    A hole at the trailing edge has nothing to its right to interpolate
    towards, so it carries the last known value forward. That is the honest
    answer — it is what the series looked like at the time — and it is what
    `np.interp` does at the boundary anyway.
    """
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
    """Clip against the spread of this window, not of the whole history."""
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
    """What to do to a window of history before fitting on it."""

    fill: GapFill = GapFill.NONE
    #: Robust deviations to clip at, or None to leave outliers alone.
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
