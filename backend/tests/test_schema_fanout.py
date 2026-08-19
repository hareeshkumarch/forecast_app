"""Reading an arbitrary upload into series a univariate model can be run over."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from app.models.enums import ForecastFrequency, MeasureAggregation
from app.schema import (
    CanonicalConfig,
    FanOutConfig,
    propose,
    run_fanout,
    to_canonical,
    validate_canonical,
)
from app.schema.contract import LAYOUT_WIDE, SINGLE_SERIES_ID
from app.schema.validation import ROUTE_FALLBACK, STATUS_REJECT

MONTHS = [date(2021, 1, 1).replace(month=(i % 12) + 1, year=2021 + i // 12) for i in range(36)]
ISO = [month.isoformat() for month in MONTHS]


def _sales(offset: float) -> list[float]:
    return [float(round(1000.0 + offset + 40 * i + 90 * (i % 12), 2)) for i in range(len(MONTHS))]


def single_series() -> pl.DataFrame:
    return pl.DataFrame({"order_date": ISO, "revenue": _sales(0.0)})


def sku_panel() -> pl.DataFrame:
    skus = ["A-100", "B-200", "C-300"]
    return pl.DataFrame(
        {
            "order_date": ISO * len(skus),
            "sku": [sku for sku in skus for _ in MONTHS],
            "units_sold": [value for index in range(len(skus)) for value in _sales(index * 500.0)],
        }
    )


def hierarchy_panel() -> pl.DataFrame:
    pairs = [("Drinks", "A-100"), ("Drinks", "B-200"), ("Snacks", "C-300")]
    return pl.DataFrame(
        {
            "order_date": ISO * len(pairs),
            "category": [category for category, _ in pairs for _ in MONTHS],
            "sku": [sku for _, sku in pairs for _ in MONTHS],
            "revenue": [value for index in range(len(pairs)) for value in _sales(index * 500.0)],
        }
    )


def wide_layout() -> pl.DataFrame:
    columns: dict[str, list] = {"sku": ["A-100", "B-200"]}
    for index, month in enumerate(MONTHS[:24]):
        columns[month.isoformat()] = [100.0 + index, 250.0 + index]
    return pl.DataFrame(columns)


def duplicated_rows() -> pl.DataFrame:
    frame = sku_panel()
    return pl.concat([frame, frame.head(4)])


def test_single_series_maps_to_one_series() -> None:
    proposal, _ = propose(single_series())

    assert proposal.date_col == "order_date"
    assert proposal.target_col == "revenue"
    assert proposal.series_keys == []
    assert proposal.frequency is ForecastFrequency.MONTHLY
    assert not proposal.needs_confirmation


def test_panel_finds_the_key_that_makes_the_grain_unique() -> None:
    proposal, frame = propose(sku_panel())

    assert proposal.date_col == "order_date"
    assert proposal.series_keys == ["sku"]
    assert proposal.series_count == 3
    assert not proposal.requires_aggregation_choice

    canonical = to_canonical(frame, CanonicalConfig.from_proposal(proposal))
    assert canonical["series_id"].n_unique() == 3


def test_hierarchy_is_read_from_containment_and_orders_the_key() -> None:
    proposal, _ = propose(hierarchy_panel())

    assert proposal.hierarchy == ["category", "sku"]
    assert proposal.series_keys == ["category", "sku"]


def test_wide_layout_is_melted_before_anything_is_read_from_it() -> None:
    proposal, frame = propose(wide_layout())

    assert proposal.layout == LAYOUT_WIDE
    assert proposal.date_col == "period"
    assert proposal.target_col == "value"
    assert proposal.series_keys == ["sku"]
    assert frame.height == 48


def test_duplicate_grain_is_asked_about_rather_than_guessed() -> None:
    proposal, _ = propose(duplicated_rows())

    assert proposal.requires_aggregation_choice
    assert proposal.needs_confirmation
    assert "duplicate_grain" in [warning.code for warning in proposal.warnings]


def test_unexpected_target_name_is_found_from_the_data() -> None:
    frame = pl.DataFrame({"periode": ISO, "wert_netto": _sales(0.0), "note": ["x"] * len(MONTHS)})
    proposal, _ = propose(frame)

    assert proposal.date_col == "periode"
    assert proposal.target_col == "wert_netto"


def test_two_plausible_targets_are_flagged_not_silently_picked() -> None:
    frame = pl.DataFrame(
        {"order_date": ISO, "net_revenue": _sales(0.0), "gross_revenue": _sales(120.0)}
    )
    proposal, _ = propose(frame)

    assert proposal.target_col in {"net_revenue", "gross_revenue"}
    assert "contested_target" in [warning.code for warning in proposal.warnings]
    assert proposal.needs_confirmation


def test_mixed_date_formats_in_one_column_still_parse() -> None:
    mixed = [
        month.isoformat() if index % 2 else month.strftime("%d/%m/%Y")
        for index, month in enumerate(MONTHS)
    ]
    proposal, frame = propose(pl.DataFrame({"date": mixed, "demand": _sales(0.0)}))

    assert proposal.date_col == "date"
    canonical = to_canonical(frame, CanonicalConfig.from_proposal(proposal))
    assert canonical.height == len(MONTHS)


def test_the_same_file_always_proposes_the_same_mapping() -> None:
    first, _ = propose(hierarchy_panel())
    second, _ = propose(hierarchy_panel())

    assert first.as_dict() == second.as_dict()


def test_short_and_intermittent_series_are_routed_to_a_fallback() -> None:
    frame = pl.concat(
        [
            sku_panel(),
            pl.DataFrame(
                {
                    "order_date": ISO[:3],
                    "sku": ["D-400"] * 3,
                    "units_sold": [5.0, 6.0, 7.0],
                }
            ),
            pl.DataFrame(
                {
                    "order_date": ISO,
                    "sku": ["E-500"] * len(MONTHS),
                    "units_sold": [0.0 if index % 10 else 12.0 for index in range(len(MONTHS))],
                }
            ),
        ]
    )
    proposal, working = propose(frame)
    canonical = to_canonical(working, CanonicalConfig.from_proposal(proposal))
    report = validate_canonical(canonical, frequency=ForecastFrequency.MONTHLY)

    by_id = report.by_id
    assert by_id["D-400"].route == ROUTE_FALLBACK
    assert "short_history" in by_id["D-400"].codes
    assert "intermittent_demand" in by_id["E-500"].codes
    assert by_id["E-500"].route == ROUTE_FALLBACK
    assert all(item.status != STATUS_REJECT for item in report.series)


def test_fan_out_returns_one_row_per_series_and_period() -> None:
    proposal, working = propose(sku_panel())
    canonical = to_canonical(working, CanonicalConfig.from_proposal(proposal))
    config = FanOutConfig(frequency=ForecastFrequency.MONTHLY, horizon=6, max_workers=3)

    result = run_fanout(canonical, config)

    assert result.forecast_series_count == 3
    assert result.forecasts.height == 3 * config.horizon
    assert not result.errors


def test_bottom_up_rolls_leaves_into_their_parent_levels() -> None:
    proposal, working = propose(hierarchy_panel())
    canonical = to_canonical(working, CanonicalConfig.from_proposal(proposal))
    config = FanOutConfig(
        frequency=ForecastFrequency.MONTHLY,
        horizon=4,
        hierarchy=proposal.hierarchy,
        aggregate_to_parents=True,
    )

    result = run_fanout(canonical, config)

    assert result.forecasts.height == 3 * config.horizon
    assert set(result.parents["series_id"].unique()) == {"Drinks", "Snacks"}
    assert result.parents.height == 2 * config.horizon


def test_a_single_bad_series_does_not_stop_the_run() -> None:
    canonical = pl.DataFrame(
        {
            "series_id": ["good"] * len(MONTHS) + ["bad"],
            "ds": [*MONTHS, MONTHS[0]],
            "y": [*_sales(0.0), 1.0],
        }
    ).with_columns(pl.col("ds").cast(pl.Date), pl.col("y").cast(pl.Float64))

    result = run_fanout(canonical, FanOutConfig(frequency=ForecastFrequency.MONTHLY, horizon=3))

    assert result.forecast_series_count == 1
    assert [error.series_id for error in result.errors] == ["bad"]
    assert result.errors[0].code == "no_history"


@pytest.mark.parametrize(
    "aggregation", [MeasureAggregation.SUM, MeasureAggregation.MEAN, MeasureAggregation.LAST]
)
def test_an_aggregation_choice_resolves_a_duplicated_grain(
    aggregation: MeasureAggregation,
) -> None:
    proposal, working = propose(duplicated_rows())
    config = CanonicalConfig.from_proposal(proposal).model_copy(update={"aggregation": aggregation})

    canonical = to_canonical(working, config)

    assert canonical.filter(pl.col("series_id") == "A-100").height == len(MONTHS)


def test_single_series_canonical_frame_carries_the_placeholder_id() -> None:
    proposal, working = propose(single_series())
    canonical = to_canonical(working, CanonicalConfig.from_proposal(proposal))

    assert canonical["series_id"].unique().to_list() == [SINGLE_SERIES_ID]
