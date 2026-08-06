from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from app.forecasting.frequency import seasonal_period
from app.models.enums import ForecastFrequency

FloatArray = npt.NDArray[np.float64]

#: A driver is only worth carrying if there are rows to identify it with. One
#: column per twenty observations keeps a 40-point monthly series to two and a
#: 100-point one to four, which is about where added columns stop paying for
#: the rows they cost.
OBSERVATIONS_PER_DRIVER = 20
MAX_DRIVERS = 4

#: Enough of the series has to survive the lag to fit anything at all.
MIN_ROWS_AFTER_LAG = 12


@dataclass(slots=True)
class DriverLink:
    """One column of the customer's data, and the lag at which it leads."""

    name: str
    lag: int
    #: Rank correlation with the target's period-on-period change. Signed, so
    #: the direction can be reported; ranked on magnitude.
    strength: float

    @property
    def direction(self) -> str:
        return "up" if self.strength >= 0 else "down"


@dataclass(slots=True)
class DriverPanel:
    """
    Candidate leading indicators, already on the target's own calendar.

    Only lags the forecast can actually know are offered. A driver at lag L is
    knowable for the first L steps ahead, because step h needs its value L
    periods before — so restricting L to at least the horizon means every step
    of the forecast reads a value that has already happened. Anything shorter
    would need the driver's own future, which is a forecast of a forecast and
    is not what this is for.
    """

    links: list[DriverLink] = field(default_factory=list)
    #: One column per link, aligned to the calendar it was built against.
    series: dict[str, FloatArray] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.links)

    @property
    def names(self) -> list[str]:
        return [link.name for link in self.links]

    def columns(self, length: int) -> dict[str, FloatArray]:
        """
        The lagged columns for a calendar of `length` periods.

        A row `length` beyond the panel is the caller building a future row.
        Only `raw[:length - lag]` is ever copied, so the furthest value any row
        can reach is `lag` periods before it — which is what makes this safe
        during a backtest, where the panel spans the whole series but the model
        is only allowed to have seen the part before the cut.
        """
        out: dict[str, FloatArray] = {}

        for link in self.links:
            raw = self.series.get(link.name)
            if raw is None:
                continue

            shifted = np.full(length, np.nan)
            available = min(length - link.lag, raw.size)
            if available > 0:
                shifted[link.lag : link.lag + available] = raw[:available]
            out[f"driver_{link.name}_lag_{link.lag}"] = shifted

        return out


#: What one step of each frequency is called, singular and plural. Saying "6
#: periods earlier" to a planner looking at months is the kind of phrasing that
#: makes a product feel like somebody's internal tool.
PERIOD_WORDS: dict[ForecastFrequency, tuple[str, str]] = {
    ForecastFrequency.DAILY: ("day", "days"),
    ForecastFrequency.WEEKLY: ("week", "weeks"),
    ForecastFrequency.MONTHLY: ("month", "months"),
    ForecastFrequency.QUARTERLY: ("quarter", "quarters"),
}


def describe(links: list[DriverLink], frequency: ForecastFrequency, target: str) -> str:
    """
    The leading columns in a sentence, for the reader who wants to know what
    the forecast looked at besides the target's own past.
    """
    if not links:
        return ""

    singular, plural = PERIOD_WORDS.get(frequency, ("period", "periods"))

    def phrase(link: DriverLink) -> str:
        unit = singular if link.lag == 1 else plural
        return f"{link.name} from {link.lag} {unit} earlier"

    if len(links) == 1:
        listed = phrase(links[0])
    else:
        listed = ", ".join(phrase(link) for link in links[:-1]) + f" and {phrase(links[-1])}"

    return f"It also read {listed}, which your history shows moving before {target} does."


def _spearman(left: FloatArray, right: FloatArray) -> float:
    """Rank correlation, which does not care that a driver is on another scale."""
    usable = np.isfinite(left) & np.isfinite(right)
    if int(usable.sum()) < MIN_ROWS_AFTER_LAG:
        return 0.0

    x, y = left[usable], right[usable]
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        return 0.0

    rank_x = np.argsort(np.argsort(x)).astype(float)
    rank_y = np.argsort(np.argsort(y)).astype(float)
    rank_x -= rank_x.mean()
    rank_y -= rank_y.mean()

    denominator = math.sqrt(float(rank_x @ rank_x) * float(rank_y @ rank_y))
    if denominator == 0.0:
        return 0.0
    return float(rank_x @ rank_y) / denominator


def significant_at(n_pairs: int) -> float:
    """
    The correlation a driver has to clear before it is worth a column.

    Derived rather than picked: this is the two-sided 5% critical value for a
    rank correlation on `n_pairs` points, so the bar tightens as the series
    gets shorter instead of letting noise through on the series least able to
    afford it.
    """
    if n_pairs < MIN_ROWS_AFTER_LAG:
        return 1.0
    return min(1.0, 1.96 / math.sqrt(n_pairs - 1))


def admissible_lags(horizon: int, n_observations: int, frequency: ForecastFrequency) -> list[int]:
    """
    Lags the forecast can read without knowing the driver's future.

    The floor is the horizon. The ceiling is one seasonal cycle beyond it,
    because a relationship further back than "this time last year, plus the
    horizon" is not one this much history can tell from coincidence.
    """
    period = seasonal_period(frequency)
    ceiling = horizon + max(period, 1)
    return [
        lag for lag in range(horizon, ceiling + 1) if n_observations - lag >= MIN_ROWS_AFTER_LAG
    ]


def budget(n_observations: int) -> int:
    return max(0, min(MAX_DRIVERS, n_observations // OBSERVATIONS_PER_DRIVER))


def build_panel(
    target: FloatArray,
    candidates: dict[str, FloatArray],
    *,
    horizon: int,
    frequency: ForecastFrequency,
) -> DriverPanel:
    """
    Picks which of the customer's other numeric columns lead the target.

    Screening, not deciding: a column that gets through here has only earned a
    place in the design matrix. Whether the model is better off using it is
    settled out of sample by the tuner, which is the only test that means
    anything.

    Correlation is measured on period-on-period change rather than on level,
    because two columns that both grow with the business correlate at 0.99
    whether or not either tells you anything about the other.
    """
    n = int(target.size)
    allowance = budget(n)
    if allowance == 0 or not candidates:
        return DriverPanel()

    lags = admissible_lags(horizon, n, frequency)
    if not lags:
        return DriverPanel()

    target_change = np.diff(target, prepend=np.nan)

    found: list[tuple[DriverLink, FloatArray]] = []

    for name, raw in candidates.items():
        column = np.asarray(raw, dtype=np.float64)
        if column.size != n or not np.isfinite(column).any():
            continue

        change = np.diff(column, prepend=np.nan)

        best: tuple[float, int] | None = None
        for lag in lags:
            shifted = np.full(n, np.nan)
            shifted[lag:] = change[: n - lag]

            strength = _spearman(shifted, target_change)
            pairs = int((np.isfinite(shifted) & np.isfinite(target_change)).sum())
            if abs(strength) < significant_at(pairs):
                continue
            if best is None or abs(strength) > abs(best[0]):
                best = (strength, lag)

        if best is not None:
            found.append((DriverLink(name=name, lag=best[1], strength=best[0]), column))

    found.sort(key=lambda item: abs(item[0].strength), reverse=True)
    kept = found[:allowance]

    return DriverPanel(
        links=[link for link, _ in kept],
        series={link.name: column for link, column in kept},
    )
