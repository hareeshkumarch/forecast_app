from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

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

    def project_future(self, horizon: int, frequency: ForecastFrequency) -> DriverPanel:
        """Carry each driver forward `horizon` steps on its own trend and season."""
        if horizon <= 0 or not self.series:
            return DriverPanel(links=list(self.links), series=dict(self.series))

        period = seasonal_period(frequency)
        projected_series: dict[str, FloatArray] = {}

        for name, values in self.series.items():
            # Fit against where the observed points actually sit rather than against
            # their compressed positions: every dropped gap would otherwise pull the
            # projection one step earlier and skew both the slope and the phase.
            observed = np.flatnonzero(np.isfinite(values)).astype(float)
            finite = values[observed.astype(int)] if observed.size else values[:0]
            future_x = np.arange(values.size, values.size + horizon, dtype=float)

            if finite.size < 3:
                filler = float(finite[-1]) if finite.size else 0.0
                projected_series[name] = np.concatenate([values, np.full(horizon, filler)])
                continue

            if finite.size >= 4:
                slope, intercept = np.polyfit(observed, finite, 1)
            else:
                slope, intercept = 0.0, float(np.mean(finite))

            future_trend = slope * future_x + intercept

            if period > 1 and finite.size >= 2 * period:
                detrended = finite - (slope * observed + intercept)
                phases = (observed % period).astype(int)
                seasonal_pattern = np.array(
                    [
                        float(np.mean(detrended[phases == phase]))
                        if np.any(phases == phase)
                        else 0.0
                        for phase in range(period)
                    ]
                )
                seasonal_pattern -= np.mean(seasonal_pattern)
                future_seasonal = np.array(
                    [seasonal_pattern[int(step) % period] for step in future_x]
                )
            else:
                future_seasonal = np.zeros(horizon)

            projected_series[name] = np.concatenate([values, future_trend + future_seasonal])

        return DriverPanel(links=list(self.links), series=projected_series)


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


@dataclass(slots=True)
class DriverSource:
    """The candidate columns, and the calendar they are aligned to.

    Which column leads the target, and by how many periods, is discovered by
    correlating them — so discovering it once over the whole history chooses
    the drivers with the validation target in hand. On a wide panel of
    candidates that is enough on its own to make a backtest look good: some
    column always correlates with the periods being scored.

    So discovery is asked for per window. `panel_for` ranks the candidates
    against the training window alone, then carries the chosen columns past it
    — a driver that leads the target is by definition observed over the
    periods being predicted, which is the whole reason it is worth reading.
    """

    periods: list[date]
    columns: dict[str, FloatArray]
    horizon: int
    frequency: ForecastFrequency
    _at: dict[date, int] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._at = {period: index for index, period in enumerate(self.periods)}

    def __bool__(self) -> bool:
        return bool(self.columns)

    def panel_for(self, target: FloatArray, window: list[date]) -> DriverPanel:
        if not self.columns or not window:
            return DriverPanel()

        start = self._at.get(window[0])
        if start is None:
            return DriverPanel()
        stop = start + len(window)

        discovered = build_panel(
            target,
            {name: column[start:stop] for name, column in self.columns.items()},
            horizon=self.horizon,
            frequency=self.frequency,
        )
        if not discovered:
            return DriverPanel()

        # Sliced from the window's own start, so index 0 of the panel is index
        # 0 of the training data. A rolling fold starts partway through the
        # history, and a panel indexed from the series start would hand every
        # model driver values from the wrong periods.
        return DriverPanel(
            links=discovered.links,
            series={link.name: self.columns[link.name][start:] for link in discovered.links},
        )
