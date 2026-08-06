from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from app.forecasting.frequency import seasonal_period
from app.models.enums import ForecastFrequency

FloatArray = npt.NDArray[np.float64]

OBSERVATIONS_PER_DRIVER = 20
MAX_DRIVERS = 4

MIN_ROWS_AFTER_LAG = 12


@dataclass(slots=True)
class DriverLink:
    name: str
    lag: int
    strength: float

    @property
    def direction(self) -> str:
        return "up" if self.strength >= 0 else "down"


@dataclass(slots=True)
class DriverPanel:
    links: list[DriverLink] = field(default_factory=list)
    series: dict[str, FloatArray] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.links)

    @property
    def names(self) -> list[str]:
        return [link.name for link in self.links]

    def columns(self, length: int) -> dict[str, FloatArray]:
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


PERIOD_WORDS: dict[ForecastFrequency, tuple[str, str]] = {
    ForecastFrequency.DAILY: ("day", "days"),
    ForecastFrequency.WEEKLY: ("week", "weeks"),
    ForecastFrequency.MONTHLY: ("month", "months"),
    ForecastFrequency.QUARTERLY: ("quarter", "quarters"),
}


def describe(links: list[DriverLink], frequency: ForecastFrequency, target: str) -> str:
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
    if n_pairs < MIN_ROWS_AFTER_LAG:
        return 1.0
    return min(1.0, 1.96 / math.sqrt(n_pairs - 1))


def admissible_lags(horizon: int, n_observations: int, frequency: ForecastFrequency) -> list[int]:
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
