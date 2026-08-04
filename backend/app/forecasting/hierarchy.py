from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

# Below this the segment forecasts carry no information about the split, so
# falling back to the historical shares is more honest than scaling noise.
MIN_RECONCILABLE_TOTAL = 1e-9


def reconcile_to_total(
    segment_forecasts: list[FloatArray],
    total_forecast: FloatArray,
    shares: list[float],
) -> list[FloatArray]:
    """
    Scales independently forecast segments so they add up to the top line.

    The total is forecast directly and is the more reliable of the two —
    aggregation cancels noise that each segment carries on its own — so it is
    kept, and the segments supply the split. Each segment keeps its own shape:
    one growing while another shrinks stays visible, which is exactly what a
    proportional split of the total could never express.

    Where the segments sum to nothing in a period there is no split to take, so
    the historical shares stand in.
    """
    if not segment_forecasts:
        return []

    stacked = np.vstack([np.asarray(f, dtype=float) for f in segment_forecasts])
    total = np.asarray(total_forecast, dtype=float)

    # A negative segment forecast would invert the split, so clip before
    # apportioning and let the total carry the sign.
    stacked = np.clip(stacked, 0.0, None)
    column_sums = stacked.sum(axis=0)

    fallback = np.asarray(shares, dtype=float).reshape(-1, 1)
    if fallback.sum() > 0:
        fallback = fallback / fallback.sum()
    else:
        fallback = np.full((stacked.shape[0], 1), 1.0 / stacked.shape[0])

    usable = column_sums > MIN_RECONCILABLE_TOTAL
    weights = np.where(usable, stacked / np.where(usable, column_sums, 1.0), fallback)

    return list(weights * total)


def bottom_up(segment_forecasts: list[FloatArray]) -> FloatArray:
    """The total implied by the segments, for reporting how far it sits from the direct one."""
    if not segment_forecasts:
        return np.zeros(0)
    return np.vstack([np.asarray(f, dtype=float) for f in segment_forecasts]).sum(axis=0)


def coherence_gap(segment_forecasts: list[FloatArray], total_forecast: FloatArray) -> float:
    """
    How far the segments' own sum sits from the directly forecast total, as a
    fraction of the total. A large gap means the two levels disagree about
    where the business is going, which is worth surfacing rather than hiding
    behind the rescale.
    """
    if not segment_forecasts:
        return 0.0

    implied = bottom_up(segment_forecasts).sum()
    direct = float(np.asarray(total_forecast, dtype=float).sum())
    if abs(direct) < MIN_RECONCILABLE_TOTAL:
        return 0.0
    return float(abs(implied - direct) / abs(direct))
