from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from app.forecasting.frequency import seasonal_period
from app.models.enums import ForecastFrequency

FloatArray = npt.NDArray[np.float64]


@dataclass(slots=True)
class Driver:
    name: str
    impact_value: float
    impact_pct: float
    change_vs_last_year: float | None
    direction: str
    trend: list[float]
    method: str


def _direction(value: float) -> str:
    if value > 1e-9:
        return "up"
    if value < -1e-9:
        return "down"
    return "flat"


def _sparkline(values: FloatArray, points: int = 12) -> list[float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return []
    if finite.size <= points:
        return [round(float(v), 4) for v in finite]

    edges = np.linspace(0, finite.size, points + 1).astype(int)
    return [
        round(float(np.mean(finite[edges[i] : edges[i + 1]])), 4)
        for i in range(points)
        if edges[i + 1] > edges[i]
    ]


def decompose_drivers(
    history: FloatArray,
    forecast: FloatArray,
    frequency: ForecastFrequency,
    *,
    quantity: FloatArray | None = None,
) -> list[Driver]:
    history = np.asarray(history, dtype=float).ravel()
    forecast = np.asarray(forecast, dtype=float).ravel()
    horizon = forecast.size

    if history.size == 0 or horizon == 0:
        return []


    window = min(horizon, history.size)
    baseline = history[-window:]
    baseline_total = float(np.sum(baseline))
    forecast_total = float(np.sum(forecast))
    total_movement = forecast_total - baseline_total

    trend_component, seasonal_component, residual = _decompose(history, frequency)

    drivers: list[Driver] = []


    slope = _trend_slope(trend_component)
    volume_impact = slope * horizon * (horizon + 1) / 2.0
    drivers.append(
        Driver(
            name="Volume Growth",
            impact_value=volume_impact,
            impact_pct=0.0,
            change_vs_last_year=_yoy(history, frequency),
            direction=_direction(volume_impact),
            trend=_sparkline(trend_component),
            method="stl_trend_slope",
        )
    )


    period = seasonal_period(frequency)
    if seasonal_component.size >= period:
        phase = history.size % period
        seasonal_forward = np.array(
            [seasonal_component[-period:][(phase + i) % period] for i in range(horizon)]
        )
        seasonal_impact = float(np.sum(seasonal_forward))
        seasonal_method = "stl_seasonal"
    else:
        seasonal_impact = 0.0
        seasonal_forward = np.zeros(horizon)
        seasonal_method = "insufficient_history"

    drivers.append(
        Driver(
            name="Seasonality",
            impact_value=seasonal_impact,
            impact_pct=0.0,
            change_vs_last_year=None,
            direction=_direction(seasonal_impact),
            trend=_sparkline(seasonal_component if seasonal_component.size else seasonal_forward),
            method=seasonal_method,
        )
    )


    if quantity is not None and quantity.size == history.size and np.all(quantity[-window:] > 0):
        unit_value = history[-window:] / quantity[-window:]
        prior = history[-2 * window : -window] / quantity[-2 * window : -window] if history.size >= 2 * window and np.all(quantity[-2 * window : -window] > 0) else unit_value
        price_delta = float(np.mean(unit_value) - np.mean(prior))
        price_impact = price_delta * float(np.sum(quantity[-window:]))
        price_method = "unit_value_delta"
    else:

        level_shift = float(np.mean(forecast) - np.mean(baseline))
        price_impact = (level_shift - slope * horizon / 2.0) * horizon * 0.5
        price_method = "residual_level_shift"

    drivers.append(
        Driver(
            name="Price Changes",
            impact_value=price_impact,
            impact_pct=0.0,
            change_vs_last_year=None,
            direction=_direction(price_impact),
            trend=_sparkline(history[-min(history.size, 24) :]),
            method=price_method,
        )
    )


    market_impact = total_movement - volume_impact - seasonal_impact - price_impact


    promo_share = _promotional_share(residual)
    promo_impact = market_impact * promo_share
    market_impact -= promo_impact

    drivers.append(
        Driver(
            name="Market Growth",
            impact_value=market_impact,
            impact_pct=0.0,
            change_vs_last_year=_yoy(history, frequency),
            direction=_direction(market_impact),
            trend=_sparkline(trend_component),
            method="residual_attribution",
        )
    )

    drivers.append(
        Driver(
            name="Promotions",
            impact_value=promo_impact,
            impact_pct=0.0,
            change_vs_last_year=None,
            direction=_direction(promo_impact),
            trend=_sparkline(residual),
            method="positive_residual_spikes",
        )
    )


    denominator = sum(abs(d.impact_value) for d in drivers) or 1.0
    for driver in drivers:
        driver.impact_pct = round(driver.impact_value / denominator * 100.0, 2)

    drivers.sort(key=lambda d: abs(d.impact_value), reverse=True)
    return drivers


def _decompose(
    values: FloatArray, frequency: ForecastFrequency
) -> tuple[FloatArray, FloatArray, FloatArray]:
    period = seasonal_period(frequency)

    if values.size >= 2 * period + 1:
        try:
            from statsmodels.tsa.seasonal import STL

            stl = STL(values, period=period, robust=True).fit()
            return (
                np.asarray(stl.trend, dtype=float),
                np.asarray(stl.seasonal, dtype=float),
                np.asarray(stl.resid, dtype=float),
            )
        except Exception:  # noqa: BLE001 — fall through to the simple path
            pass

    window = min(max(3, period), values.size)
    kernel = np.ones(window) / window
    trend = np.convolve(values, kernel, mode="same")
    residual = values - trend
    return trend, np.zeros(0), residual


def _trend_slope(trend: FloatArray) -> float:
    finite = trend[np.isfinite(trend)]
    if finite.size < 3:
        return 0.0
    tail = finite[-max(3, finite.size // 2) :]
    x = np.arange(tail.size, dtype=float)
    return float(np.polyfit(x, tail, 1)[0])


def _promotional_share(residual: FloatArray) -> float:
    finite = residual[np.isfinite(residual)]
    if finite.size < 4:
        return 0.0
    threshold = float(np.std(finite))
    if threshold == 0:
        return 0.0
    spikes = finite[finite > threshold]
    if spikes.size == 0:
        return 0.0
    share = float(np.sum(spikes) / np.sum(np.abs(finite)))
    return min(max(share, 0.0), 0.5)


def _yoy(values: FloatArray, frequency: ForecastFrequency) -> float | None:
    period = seasonal_period(frequency)
    if values.size < 2 * period:
        return None
    recent = float(np.sum(values[-period:]))
    prior = float(np.sum(values[-2 * period : -period]))
    if prior == 0:
        return None
    return round((recent - prior) / abs(prior) * 100.0, 2)
