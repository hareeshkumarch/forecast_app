from __future__ import annotations

from datetime import date, timedelta

from app.models.enums import ForecastFrequency

SEASONAL_PERIODS: dict[ForecastFrequency, int] = {
    ForecastFrequency.DAILY: 7,
    ForecastFrequency.WEEKLY: 52,
    ForecastFrequency.MONTHLY: 12,
    ForecastFrequency.QUARTERLY: 4,
}

SEASONAL_CANDIDATES: dict[ForecastFrequency, tuple[int, ...]] = {
    ForecastFrequency.DAILY: (7, 14, 30, 91, 365),
    ForecastFrequency.WEEKLY: (4, 13, 26, 52),
    ForecastFrequency.MONTHLY: (3, 4, 6, 12),
    ForecastFrequency.QUARTERLY: (4,),
}

APPROX_DAYS: dict[ForecastFrequency, float] = {
    ForecastFrequency.DAILY: 1.0,
    ForecastFrequency.WEEKLY: 7.0,
    ForecastFrequency.MONTHLY: 30.44,
    ForecastFrequency.QUARTERLY: 91.31,
}

MIN_OBSERVATIONS: dict[ForecastFrequency, int] = {
    ForecastFrequency.DAILY: 14,
    ForecastFrequency.WEEKLY: 12,
    ForecastFrequency.MONTHLY: 8,
    ForecastFrequency.QUARTERLY: 6,
}


def seasonal_period(frequency: ForecastFrequency) -> int:
    return SEASONAL_PERIODS[frequency]


def periods_per_year(frequency: ForecastFrequency) -> int:
    return max(1, round(365.25 / APPROX_DAYS[frequency]))


def comparison_window(frequency: ForecastFrequency, n_observations: int) -> int:
    year = periods_per_year(frequency)
    if n_observations >= 2 * year:
        return year
    return max(1, n_observations // 2)


def candidate_periods(frequency: ForecastFrequency, n_observations: int) -> list[int]:
    return [
        period
        for period in SEASONAL_CANDIDATES[frequency]
        if period >= 2 and n_observations >= 2 * period + 1
    ]


def min_observations(frequency: ForecastFrequency) -> int:
    return MIN_OBSERVATIONS[frequency]


def add_periods(anchor: date, count: int, frequency: ForecastFrequency) -> date:
    if frequency is ForecastFrequency.DAILY:
        return anchor + timedelta(days=count)
    if frequency is ForecastFrequency.WEEKLY:
        return anchor + timedelta(weeks=count)

    months = count * (3 if frequency is ForecastFrequency.QUARTERLY else 1)
    total = (anchor.year * 12 + anchor.month - 1) + months
    year, month = divmod(total, 12)
    month += 1

    if month == 12:
        last_day = 31
    else:
        last_day = (date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(anchor.day, last_day))


def future_periods(last_period: date, horizon: int, frequency: ForecastFrequency) -> list[date]:
    return [add_periods(last_period, step, frequency) for step in range(1, horizon + 1)]


def period_start(day: date, frequency: ForecastFrequency) -> date:
    if frequency is ForecastFrequency.DAILY:
        return day
    if frequency is ForecastFrequency.WEEKLY:
        return day - timedelta(days=day.weekday())
    if frequency is ForecastFrequency.QUARTERLY:
        return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
    return date(day.year, day.month, 1)


def period_end(period: date, frequency: ForecastFrequency) -> date:
    return add_periods(period_start(period, frequency), 1, frequency) - timedelta(days=1)


def period_is_settled(period: date, covered_through: date, frequency: ForecastFrequency) -> bool:
    if period_end(period, frequency) <= covered_through:
        return True
    return period_start(period, frequency) < period_start(covered_through, frequency)


def infer_frequency(periods: list[date]) -> ForecastFrequency | None:
    if len(periods) < 3:
        return None

    ordered = sorted(set(periods))
    if len(ordered) < 3:
        return None

    gaps = sorted((ordered[i + 1] - ordered[i]).days for i in range(len(ordered) - 1))
    median_gap = gaps[len(gaps) // 2]
    if median_gap <= 0:
        return None

    best: ForecastFrequency | None = None
    best_error = float("inf")
    for frequency, days in APPROX_DAYS.items():
        error = abs(median_gap - days) / days
        if error < best_error:
            best_error, best = error, frequency

    return best if best_error <= 0.4 else None
