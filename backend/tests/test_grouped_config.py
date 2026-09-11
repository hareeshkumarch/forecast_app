from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from app.datasets import queries
from app.forecasting.engine import SegmentInput, assemble_grouped, fit_leaf
from app.forecasting.preparation import Preparation
from app.models.enums import ForecastFrequency, GapFill, MeasureAggregation

MONTHLY = ForecastFrequency.MONTHLY


def months(n: int, start: date = date(2022, 1, 1)) -> list[date]:
    from app.forecasting.frequency import add_periods

    return [add_periods(start, i, MONTHLY) for i in range(n)]


def _parquet(tmp_path, rows: list[tuple[str, str, float]]):
    frame = pl.DataFrame(
        {
            "period": [r[0] for r in rows],
            "sku": [r[1] for r in rows],
            "units": [r[2] for r in rows],
        }
    )
    path = tmp_path / "panel.parquet"
    frame.write_parquet(path)
    return path


def test_a_period_with_no_row_is_not_a_zero(tmp_path) -> None:
    calendar = months(6)
    rows = [
        (period.isoformat(), "A", 100.0) for index, period in enumerate(calendar) if index != 3
    ] + [(period.isoformat(), "B", 50.0) for period in calendar]

    grouped = queries.aggregate_grouped(
        _parquet(tmp_path, rows), "period", "units", ["sku"], MONTHLY
    )
    a = next(series for series in grouped if series.label == "A")

    assert np.isnan(a.values[3]), "an unreported period is unreported, not zero"
    assert all(np.isfinite(v) for i, v in enumerate(a.values) if i != 3)


def test_the_segments_query_agrees_with_the_run_on_how_a_measure_adds_up(tmp_path) -> None:
    calendar = months(3)
    rows = [(period.isoformat(), "North", value) for period in calendar for value in (10.0, 30.0)]

    path = _parquet(tmp_path, rows)
    summed = queries.aggregate_segments(path, "period", "units", "sku", MONTHLY)
    averaged = queries.aggregate_segments(
        path, "period", "units", "sku", MONTHLY, aggregation=MeasureAggregation.MEAN
    )

    assert summed[0].values[0] == pytest.approx(40.0)
    assert averaged[0].values[0] == pytest.approx(20.0)


def test_a_grouped_series_is_filled_by_the_rule_the_run_asked_for() -> None:
    interpolated = fit_leaf(
        "A",
        months(36),
        [float("nan") if i == 10 else 100.0 + i for i in range(36)],
        MONTHLY,
        3,
        None,
        0.8,
        Preparation(fill=GapFill.INTERPOLATE),
    )
    zeroed = fit_leaf(
        "A",
        months(36),
        [float("nan") if i == 10 else 100.0 + i for i in range(36)],
        MONTHLY,
        3,
        None,
        0.8,
        Preparation(fill=GapFill.ZERO),
    )

    assert interpolated.fitted and zeroed.fitted
    assert interpolated.wmape != zeroed.wmape


def test_asking_for_no_fill_leaves_the_series_unforecastable_rather_than_guessing() -> None:
    values = [float("nan") if i == 10 else 100.0 + i for i in range(36)]

    fit = fit_leaf("A", months(36), values, MONTHLY, 3, None, 0.8, Preparation(fill=GapFill.NONE))

    assert not fit.fitted
    assert fit.blocked_reason is not None
    assert "no data" in fit.blocked_reason


def _leaves(totals: list[float]) -> list[SegmentInput]:
    calendar = months(12)
    return [
        SegmentInput(
            label=f"S{index}",
            current_total=total,
            prior_total=None,
            periods=calendar,
            values=[total / 12] * 12,
            key={"sku": f"S{index}"},
        )
        for index, total in enumerate(totals)
    ]


def test_a_breakdown_of_a_negative_total_still_produces_series() -> None:
    leaves = _leaves([-400.0, -100.0, 100.0])
    fits = [
        type(
            "Fit",
            (),
            {
                "label": leaf.label,
                "fitted": False,
                "blocked_reason": "x",
                "banded": False,
                "forecast": None,
                "lower": None,
                "upper": None,
                "model": None,
                "wmape": None,
                "mase": None,
                "folds": 0,
                "accuracy": None,
            },
        )()
        for leaf in leaves
    ]

    results = assemble_grouped(leaves, fits, ["sku"], np.full(3, -50.0))

    assert results, "a negative total is still a total"
    labels = {row.label for row in results}
    assert {"S0", "S1", "S2"} <= labels


def test_series_that_are_all_zero_share_the_total_equally() -> None:
    leaves = _leaves([0.0, 0.0])
    fits = [
        type(
            "Fit",
            (),
            {
                "label": leaf.label,
                "fitted": False,
                "blocked_reason": "x",
                "banded": False,
                "forecast": None,
                "lower": None,
                "upper": None,
                "model": None,
                "wmape": None,
                "mase": None,
                "folds": 0,
                "accuracy": None,
            },
        )()
        for leaf in leaves
    ]

    results = assemble_grouped(leaves, fits, ["sku"], np.full(3, 90.0))

    leaves_out = [row for row in results if row.level > 0 or row.label.startswith("S")]
    assert leaves_out, "an all-zero breakdown is still a breakdown"


def test_a_driver_is_aggregated_by_what_it_is_not_by_what_the_target_is(tmp_path) -> None:
    calendar = months(4)
    frame = pl.DataFrame(
        {
            "period": [p.isoformat() for p in calendar for _ in range(4)],
            "revenue": [100.0] * 16,
            "conversion_rate": [0.25] * 16,
        }
    )
    path = tmp_path / "drivers.parquet"
    frame.write_parquet(path)

    from app.datasets.profiler import natural_aggregation

    columns = ["conversion_rate"]
    drivers = queries.aggregate_candidate_drivers(
        path,
        "period",
        columns,
        MONTHLY,
        calendar,
        aggregation=MeasureAggregation.SUM,
        per_column={name: natural_aggregation(name) for name in columns},
    )

    assert drivers["conversion_rate"][0] == pytest.approx(
        0.25
    ), "a rate is the level it was, not four times it"


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("revenue", MeasureAggregation.SUM),
        ("units_sold", MeasureAggregation.SUM),
        ("order_count", MeasureAggregation.SUM),
        ("conversion_rate", MeasureAggregation.MEAN),
        ("avg_basket", MeasureAggregation.MEAN),
        ("price_index", MeasureAggregation.MEAN),
        ("margin_pct", MeasureAggregation.MEAN),
        ("temperature", MeasureAggregation.MEAN),
        ("revenue_per_store", MeasureAggregation.MEAN),
        ("total_price", MeasureAggregation.SUM),
    ],
)
def test_how_a_column_adds_up_is_read_from_its_name(
    column: str, expected: MeasureAggregation
) -> None:
    from app.datasets.profiler import natural_aggregation

    assert natural_aggregation(column) is expected


def test_a_series_that_never_reported_a_period_rolls_up_as_unreported() -> None:
    from app.forecasting.engine import _sum_histories

    both_missing = _sum_histories([np.array([1.0, np.nan, 3.0]), np.array([2.0, np.nan, 4.0])])
    one_missing = _sum_histories([np.array([1.0, np.nan, 3.0]), np.array([2.0, 5.0, 4.0])])

    assert np.isnan(both_missing[1]), "no child reported it, so the parent did not either"
    assert one_missing[1] == pytest.approx(5.0), "the parent observed what its children did"
