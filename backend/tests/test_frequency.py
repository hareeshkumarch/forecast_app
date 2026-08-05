"""
The calendar, and the one question scoring depends on: is this period over?

Two implementations decide which period a date belongs to — Python's, when a
forecast is scored, and DuckDB's `date_trunc`, when the actuals are read. They
have to agree on every frequency or the two halves of a comparison line up
against different months, so they are held against each other here rather than
assumed to match.
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest

from app.datasets.queries import DATE_TRUNC_PART
from app.forecasting.frequency import (
    add_periods,
    period_end,
    period_is_settled,
    period_start,
)
from app.models.enums import ForecastFrequency

DAILY = ForecastFrequency.DAILY
WEEKLY = ForecastFrequency.WEEKLY
MONTHLY = ForecastFrequency.MONTHLY
QUARTERLY = ForecastFrequency.QUARTERLY

#: Leap day, a month end, a year end, a Sunday, a Monday, a quarter boundary.
AWKWARD_DAYS = [
    date(2024, 2, 29),
    date(2023, 2, 28),
    date(2024, 1, 31),
    date(2024, 12, 31),
    date(2025, 1, 1),
    date(2024, 6, 30),
    date(2024, 7, 1),
    date(2024, 3, 3),
    date(2024, 3, 4),
]


@pytest.mark.parametrize("frequency", list(ForecastFrequency))
@pytest.mark.parametrize("day", AWKWARD_DAYS)
def test_python_and_duckdb_agree_on_which_period_a_date_is_in(
    frequency: ForecastFrequency, day: date
) -> None:
    part = DATE_TRUNC_PART[frequency]
    with duckdb.connect(database=":memory:") as connection:
        row = connection.execute(
            f"SELECT date_trunc('{part}', DATE '{day.isoformat()}')"
        ).fetchone()

    assert row is not None
    truncated = row[0]
    assert period_start(day, frequency) == (
        truncated.date() if hasattr(truncated, "date") else truncated
    ), f"{frequency.value} disagrees on {day}"


@pytest.mark.parametrize("frequency", list(ForecastFrequency))
@pytest.mark.parametrize("day", AWKWARD_DAYS)
def test_a_period_ends_the_day_before_the_next_one_starts(
    frequency: ForecastFrequency, day: date
) -> None:
    start = period_start(day, frequency)
    end = period_end(start, frequency)

    assert start <= end
    assert period_start(end, frequency) == start, "the last day is still inside the period"
    assert period_start(end + timedelta(days=1), frequency) == add_periods(start, 1, frequency)


def test_a_period_is_settled_once_the_data_reaches_its_last_day() -> None:
    january = date(2024, 1, 1)

    assert not period_is_settled(january, date(2024, 1, 30), MONTHLY)
    assert period_is_settled(january, date(2024, 1, 31), MONTHLY)
    assert period_is_settled(january, date(2024, 5, 9), MONTHLY)


def test_a_period_is_settled_once_a_later_one_has_data() -> None:
    """
    Monthly extracts stamp every row on the first of the month. Requiring the
    31st would mean such a file never settles a single period, however old.
    """
    january = date(2024, 1, 1)

    assert period_is_settled(january, date(2024, 2, 1), MONTHLY)
    assert not period_is_settled(date(2024, 2, 1), date(2024, 2, 1), MONTHLY)


def test_the_period_still_being_lived_through_is_never_settled() -> None:
    for frequency in ForecastFrequency:
        for day in AWKWARD_DAYS:
            current = period_start(day, frequency)
            end = period_end(current, frequency)
            if end > day:
                assert not period_is_settled(
                    current, day, frequency
                ), f"{frequency.value} settled {current} on {day}, before it finished"


def test_a_daily_period_settles_the_day_it_happens() -> None:
    # A day's end is the day itself, so daily data has nothing to wait for.
    assert period_is_settled(date(2024, 3, 4), date(2024, 3, 4), DAILY)
    assert not period_is_settled(date(2024, 3, 5), date(2024, 3, 4), DAILY)


def test_weeks_and_quarters_settle_on_their_own_boundaries() -> None:
    monday = period_start(date(2024, 3, 6), WEEKLY)
    assert period_end(monday, WEEKLY) == monday + timedelta(days=6)
    assert not period_is_settled(monday, monday + timedelta(days=5), WEEKLY)
    assert period_is_settled(monday, monday + timedelta(days=6), WEEKLY)

    q1 = period_start(date(2024, 2, 14), QUARTERLY)
    assert q1 == date(2024, 1, 1)
    assert period_end(q1, QUARTERLY) == date(2024, 3, 31)
    assert not period_is_settled(q1, date(2024, 3, 30), QUARTERLY)
    assert period_is_settled(q1, date(2024, 4, 1), QUARTERLY)
