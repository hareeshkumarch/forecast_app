"""
Reading what customers actually export.

A forecasting tool that only accepts clean floats and ISO dates accepts almost
nothing. These are the shapes real files arrive in — Excel's currency
formatting, a German ERP's decimal comma, an accounting package's parenthesised
negatives, a spreadsheet whose dates lost their formatting and came through as
serial numbers.

The date tests carry more weight than their size suggests. A number that fails
to parse is a column the user is told about; a date that parses *wrongly* is a
forecast built on the wrong periods that nobody finds out about.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl
import pytest

from app.datasets.coercion import coerce_numeric, parse_dates

DAYS = [date(2024, 1, 1) + timedelta(days=i) for i in range(400)]


def _numeric(values: list[object]) -> list[float]:
    parsed = coerce_numeric(pl.Series("revenue", values))
    assert parsed is not None, "the column should have been read as numbers"
    return [float(v) for v in parsed.values.drop_nulls().to_list()]


@pytest.mark.parametrize(
    ("label", "values", "first"),
    [
        ("plain", [1000.0, 1003.5, 1007.0], 1000.0),
        ("currency", ["$1,000.00", "$1,003.50", "$1,007.00"], 1000.0),
        ("grouped", ["1,000.00", "1,003.50", "1,007.00"], 1000.0),
        ("euro symbol", ["€1000.00", "€1003.50", "€1007.00"], 1000.0),
        ("european decimal", ["1000,00", "1003,50", "1007,00"], 1000.0),
        ("european grouped", ["1.000,00", "1.003,50", "1.007,00"], 1000.0),
        ("percent", ["10%", "20%", "30%"], 10.0),
        ("unit suffix", ["1000 kg", "1003 kg", "1007 kg"], 1000.0),
        ("quoted", ['"1000"', '"1003"', '"1007"'], 1000.0),
    ],
)
def test_the_numbers_a_spreadsheet_writes_are_read_as_numbers(
    label: str, values: list[object], first: float
) -> None:
    assert _numeric(values)[0] == pytest.approx(first), label


def test_parenthesised_negatives_come_back_negative() -> None:
    # An accounting export writes a loss as (890.00), not -890.00.
    assert _numeric(["(890.00)", "(120.50)", "(5.00)"]) == pytest.approx([-890.0, -120.5, -5.0])


def test_a_column_of_words_is_not_a_column_of_numbers() -> None:
    assert coerce_numeric(pl.Series("notes", [f"line note {i}" for i in range(50)])) is None


def test_an_order_reference_is_not_a_measure() -> None:
    assert coerce_numeric(pl.Series("order_id", [f"SO-{i:06d}" for i in range(50)])) is None


def test_a_column_of_dates_is_not_a_measure() -> None:
    assert coerce_numeric(pl.Series("d", [d.isoformat() for d in DAYS])) is None


def test_a_column_that_is_mostly_junk_is_refused() -> None:
    # Half the rows are unreadable, so no convention explains the column.
    mixed = ["n/a" if i % 2 else str(i) for i in range(100)]
    assert coerce_numeric(pl.Series("revenue", mixed)) is None


def _dates(values: list[object], **kwargs: object) -> list[date]:
    parsed = parse_dates(pl.Series("order_date", values), **kwargs)  # type: ignore[arg-type]
    assert parsed is not None, "the column should have been read as dates"
    return sorted(parsed.values.drop_nulls().to_list())


@pytest.mark.parametrize(
    ("label", "values"),
    [
        ("ISO", [d.isoformat() for d in DAYS]),
        ("US slash", [d.strftime("%m/%d/%Y") for d in DAYS]),
        ("EU slash", [d.strftime("%d/%m/%Y") for d in DAYS]),
        ("EU dot", [d.strftime("%d.%m.%Y") for d in DAYS]),
        ("year first slash", [d.strftime("%Y/%m/%d") for d in DAYS]),
        ("compact", [d.strftime("%Y%m%d") for d in DAYS]),
        ("compact integer", [int(d.strftime("%Y%m%d")) for d in DAYS]),
        ("ISO timestamp", [datetime(d.year, d.month, d.day, 9, 30).isoformat() for d in DAYS]),
        (
            "ISO timestamp with millis",
            [datetime(d.year, d.month, d.day, 9, 30).isoformat() + ".000" for d in DAYS],
        ),
        ("long month", [d.strftime("%b %d, %Y") for d in DAYS]),
        ("native", DAYS),
    ],
)
def test_the_date_shapes_a_customer_exports_are_all_read(label: str, values: list[object]) -> None:
    assert _dates(values)[0] == date(2024, 1, 1), label


def test_excel_serial_numbers_are_dates_when_the_column_says_so() -> None:
    serials = [(d - date(1899, 12, 30)).days for d in DAYS]

    assert _dates(serials, name_suggests_date=True)[0] == date(2024, 1, 1)


def test_a_bare_number_is_not_a_date_just_because_it_could_be() -> None:
    # 45,292 is a plausible Excel serial and a plausible revenue figure. Only
    # the column name separates them, and "revenue" does not vouch for a date.
    serials = [(d - date(1899, 12, 30)).days for d in DAYS]

    assert parse_dates(pl.Series("revenue", serials), name_suggests_date=False) is None


def test_unix_seconds_are_dates_when_the_column_says_so() -> None:
    stamps = [int(datetime(d.year, d.month, d.day).timestamp()) for d in DAYS]

    assert _dates(stamps, name_suggests_date=True)[0] == date(2024, 1, 1)


def test_quarters_and_iso_weeks_are_periods_too() -> None:
    quarters = [f"{d.year}Q{(d.month - 1) // 3 + 1}" for d in DAYS]
    weeks = [f"{d.year}-W{d.isocalendar()[1]:02d}" for d in DAYS]

    assert _dates(quarters)[0] == date(2024, 1, 1)
    assert _dates(weeks)[0].year == 2024


# --------------------------------------------------------- day / month order


def test_a_us_monthly_file_keeps_its_months() -> None:
    """The one that mattered: twelve months used to become twelve days.

    01/01, 02/01, 03/01 is January, February, March with the day held at the
    first. Read day-first it is the 1st, 2nd and 3rd of January — a year of
    history collapsed into a fortnight, and the frequency inferred as daily.
    """
    parsed = _dates([f"{month:02d}/01/2024" for month in range(1, 13)])

    assert [d.month for d in parsed] == list(range(1, 13))
    assert {d.day for d in parsed} == {1}


def test_a_european_monthly_file_keeps_its_months_too() -> None:
    parsed = _dates([f"01/{month:02d}/2024" for month in range(1, 13)])

    assert [d.month for d in parsed] == list(range(1, 13))
    assert {d.day for d in parsed} == {1}


def test_a_day_past_the_twelfth_settles_the_order_by_itself() -> None:
    us = parse_dates(pl.Series("d", [f"01/{day:02d}/2024" for day in range(1, 29)]))
    eu = parse_dates(pl.Series("d", [f"{day:02d}/01/2024" for day in range(1, 29)]))

    assert us is not None and us.layout == "MM/DD/YYYY" and not us.ambiguous
    assert eu is not None and eu.layout == "DD/MM/YYYY" and not eu.ambiguous


def test_a_file_that_cannot_settle_its_own_order_says_so() -> None:
    # Every value works both ways round, so no reading can be proven.
    values = [f"{day:02d}/{month:02d}/2024" for month in (1, 2, 3) for day in (1, 5, 9, 11)]

    parsed = parse_dates(pl.Series("d", values))

    assert parsed is not None
    assert parsed.ambiguous is True
    assert parsed.order_evidence, "an ambiguous read has to explain itself"


def test_the_order_can_be_set_by_hand_when_the_data_cannot_prove_it() -> None:
    values = [f"{day:02d}/{month:02d}/2024" for month in (1, 2, 3) for day in (1, 5, 9, 11)]

    day_first = parse_dates(pl.Series("d", values), day_first=True)
    month_first = parse_dates(pl.Series("d", values), day_first=False)

    assert day_first is not None and not day_first.ambiguous
    assert month_first is not None and not month_first.ambiguous
    assert day_first.values.drop_nulls().to_list() != month_first.values.drop_nulls().to_list()


def test_two_digit_years_land_in_this_century_not_the_first() -> None:
    # "1/5/24" parsed as %d/%m/%Y gives the year 24, and 0024-05-01 is a date
    # every downstream calculation would accept without complaint.
    parsed = _dates([f"01/{day:02d}/24" for day in range(1, 29)])

    assert all(d.year == 2024 for d in parsed)


def test_a_column_of_measurements_is_never_mistaken_for_dates() -> None:
    assert parse_dates(pl.Series("revenue", [round(1000 + i * 3.5, 2) for i in range(100)])) is None
