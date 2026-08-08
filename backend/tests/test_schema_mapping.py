"""
Working out what a customer's columns mean.

Detection that only works on the demo file is not detection. A forecasting
platform meets German ERP exports, warehouse tables with three prefixes on
every name, and spreadsheets somebody typed by hand — and the answer has to
come from what the column *is*, never from where it happens to sit in the file.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.datasets.profiler import (
    MAX_AUTO_DIMENSION_VALUES,
    profile_frame,
)
from app.models.enums import ColumnRole

ROWS = 300
DAYS = [(date(2023, 1, 1) + timedelta(days=i)).isoformat() for i in range(ROWS)]
MONEY = [round(1000 + i * 3.5, 2) for i in range(ROWS)]
QUANTITY = [10 + (i % 40) for i in range(ROWS)]
REGION = [["North", "South", "East", "West"][i % 4] for i in range(ROWS)]


def _role(columns: dict[str, list], role: ColumnRole) -> str | None:
    profile = profile_frame(pl.DataFrame(columns))
    return next((c.name for c in profile.columns if c.role is role), None)


def _target(columns: dict[str, list]) -> str | None:
    return _role(columns, ColumnRole.TARGET)


@pytest.mark.parametrize(
    ("label", "columns", "expected_time", "expected_target"),
    [
        (
            "english",
            {"order_date": DAYS, "revenue": MONEY, "units_sold": QUANTITY, "region": REGION},
            "order_date",
            "revenue",
        ),
        (
            "camelCase",
            {"orderDate": DAYS, "totalRevenue": MONEY, "unitsSold": QUANTITY},
            "orderDate",
            "totalRevenue",
        ),
        ("abbreviated", {"dt": DAYS, "rev": MONEY, "qty": QUANTITY}, "dt", "rev"),
        ("german", {"datum": DAYS, "umsatz": MONEY, "menge": QUANTITY}, "datum", "umsatz"),
        (
            "french",
            {"date_commande": DAYS, "chiffre_affaires": MONEY, "quantite": QUANTITY},
            "date_commande",
            "chiffre_affaires",
        ),
        ("spanish", {"fecha": DAYS, "ventas": MONEY, "cantidad": QUANTITY}, "fecha", "ventas"),
        (
            "warehouse",
            {
                "fct_order__order_dt": DAYS,
                "fct_order__net_rev_usd": MONEY,
                "fct_order__qty": QUANTITY,
            },
            "fct_order__order_dt",
            "fct_order__net_rev_usd",
        ),
        (
            "typed by hand",
            {"Order Date": DAYS, "Net Revenue": MONEY, "Units": QUANTITY},
            "Order Date",
            "Net Revenue",
        ),
    ],
)
def test_the_same_schema_is_read_whatever_the_columns_are_called(
    label: str, columns: dict[str, list], expected_time: str, expected_target: str
) -> None:
    profile = profile_frame(pl.DataFrame(columns))
    time = next((c.name for c in profile.columns if c.role is ColumnRole.TIME), None)
    target = next((c.name for c in profile.columns if c.role is ColumnRole.TARGET), None)

    assert (time, target) == (expected_time, expected_target), label


@pytest.mark.parametrize(
    ("measure", "count"),
    [("umsatz", "menge"), ("ventas", "cantidad"), ("rev", "qty"), ("revenue", "units")],
)
def test_the_target_does_not_change_when_the_columns_are_reordered(
    measure: str, count: str
) -> None:
    """The failure this replaces: on any schema the English hints did not cover,
    every numeric column scored the same and the stable sort handed the target
    to whichever came first in the file."""
    forwards = _target({"d": DAYS, measure: MONEY, count: QUANTITY})
    backwards = _target({"d": DAYS, count: QUANTITY, measure: MONEY})

    assert forwards == backwards == measure


def test_a_word_that_names_the_measure_beats_one_that_only_says_it_is_a_sum() -> None:
    # An invoice line total is not what the business forecasts.
    columns = {"d": DAYS, "line_total": MONEY, "order_revenue": [m * 3 for m in MONEY]}

    assert _target(columns) == "order_revenue"
    assert _target({"d": DAYS, "order_revenue": [m * 3 for m in MONEY], "line_total": MONEY}) == (
        "order_revenue"
    )


def test_a_money_column_formatted_by_excel_can_still_be_the_target() -> None:
    columns = {
        "Order Date": list(DAYS),
        "Net Revenue": [f"${1000 + i * 7.5:,.2f}" for i in range(ROWS)],
        "Units": QUANTITY,
    }

    profile = profile_frame(pl.DataFrame(columns))
    target = next(c for c in profile.columns if c.role is ColumnRole.TARGET)

    assert target.name == "Net Revenue"
    assert target.parsed_as == "currency"
    # And the stored frame holds numbers, because DuckDB reads that with
    # TRY_CAST and "$1,234.56" casts to NULL.
    assert profile.normalised is not None
    assert profile.normalised["Net Revenue"].dtype == pl.Float64


def test_an_identifier_is_not_offered_as_something_to_group_by() -> None:
    """A fifth of row count made the ceiling grow with the file: at 200k rows a
    column with 40,000 distinct values counted as a category."""
    ids = [f"C{i:06d}" for i in range(ROWS)]
    profile = profile_frame(pl.DataFrame({"d": DAYS, "revenue": MONEY, "customer_id": ids}))

    customer = next(c for c in profile.columns if c.name == "customer_id")

    assert customer.role is not ColumnRole.DIMENSION


def test_a_real_category_still_is_one() -> None:
    profile = profile_frame(pl.DataFrame({"d": DAYS, "revenue": MONEY, "region": REGION}))

    region = next(c for c in profile.columns if c.name == "region")

    assert region.role is ColumnRole.DIMENSION
    assert region.distinct_count <= MAX_AUTO_DIMENSION_VALUES


def test_a_dataset_that_had_to_guess_the_date_order_says_so() -> None:
    values = [f"{day:02d}/{month:02d}/2024" for month in (1, 2, 3) for day in (1, 5, 9, 11)]
    money = [float(i) for i in range(len(values))]

    profile = profile_frame(pl.DataFrame({"order_date": values, "revenue": money}))

    assert any("day/month" in warning for warning in profile.warnings)
    assert next(c for c in profile.columns if c.name == "order_date").order_ambiguous


def test_the_date_order_can_be_forced_when_the_file_is_ambiguous() -> None:
    values = [f"{day:02d}/{month:02d}/2024" for month in (1, 2, 3) for day in (1, 5, 9, 11)]
    money = [float(i) for i in range(len(values))]
    frame = pl.DataFrame({"order_date": values, "revenue": money})

    day_first = profile_frame(frame, day_first=True)
    month_first = profile_frame(frame, day_first=False)

    assert day_first.date_range_end != month_first.date_range_end
    assert not any("cannot say" in w for w in month_first.warnings)


def test_a_us_monthly_upload_is_still_monthly_after_profiling() -> None:
    periods = [f"{month:02d}/01/2024" for month in range(1, 13)]
    profile = profile_frame(
        pl.DataFrame({"period": periods, "revenue": [float(i) for i in range(12)]})
    )

    assert profile.date_range_start == date(2024, 1, 1)
    assert profile.date_range_end == date(2024, 12, 1)


def test_how_each_column_was_read_is_recorded() -> None:
    frame = pl.DataFrame(
        {
            "order_date": [d.replace("-", "/") for d in DAYS],
            "revenue": [f"{1000 + i:,}" for i in range(ROWS)],
        }
    )

    profile = profile_frame(frame)
    by_name = {c.name: c.parsed_as for c in profile.columns}

    assert by_name["order_date"], "a reformatted date column should say how it was read"
    assert by_name["revenue"], "a reformatted number column should say how it was read"
