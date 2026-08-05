from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.forecasting.engine import ForecastInput, SegmentInput, SeriesInput, run_forecast
from app.forecasting.frequency import add_periods
from app.forecasting.hierarchy import (
    bottom_up,
    build_tree,
    coherence_gap,
    reconcile_to_total,
    reconcile_tree,
    walk,
)
from app.models.enums import ForecastFrequency

MONTHLY = ForecastFrequency.MONTHLY
HORIZON = 6
HISTORY = 42


def periods(n: int, start: date = date(2021, 1, 1)) -> list[date]:
    return [add_periods(start, i, MONTHLY) for i in range(n)]


def test_reconciled_segments_add_up_to_the_total() -> None:
    total = np.array([100.0, 110.0, 120.0])
    segments = [np.array([30.0, 20.0, 50.0]), np.array([70.0, 90.0, 40.0])]

    reconciled = reconcile_to_total(segments, total, shares=[0.5, 0.5])

    assert np.allclose(bottom_up(reconciled), total)


def test_each_segment_keeps_its_own_shape() -> None:
    total = np.array([100.0, 100.0, 100.0])
    # One climbing, one falling, on a flat total.
    segments = [np.array([10.0, 50.0, 90.0]), np.array([90.0, 50.0, 10.0])]

    climbing, falling = reconcile_to_total(segments, total, shares=[0.5, 0.5])

    assert climbing[0] < climbing[-1], "a growing segment must still grow"
    assert falling[0] > falling[-1], "a shrinking segment must still shrink"
    assert np.allclose(climbing + falling, total)


def test_historical_shares_stand_in_where_the_segments_say_nothing() -> None:
    total = np.array([100.0, 100.0])
    segments = [np.zeros(2), np.zeros(2)]

    reconciled = reconcile_to_total(segments, total, shares=[0.75, 0.25])

    assert np.allclose(reconciled[0], [75.0, 75.0])
    assert np.allclose(reconciled[1], [25.0, 25.0])


def test_a_negative_segment_forecast_cannot_invert_the_split() -> None:
    total = np.array([100.0])
    segments = [np.array([-40.0]), np.array([60.0])]

    reconciled = reconcile_to_total(segments, total, shares=[0.5, 0.5])

    assert all(float(part[0]) >= 0.0 for part in reconciled)
    assert np.isclose(sum(float(part[0]) for part in reconciled), 100.0)


def test_coherence_gap_reports_how_far_the_levels_disagree() -> None:
    total = np.array([100.0])

    assert coherence_gap([np.array([60.0]), np.array([40.0])], total) == pytest.approx(0.0)
    assert coherence_gap([np.array([100.0]), np.array([50.0])], total) == pytest.approx(0.5)
    assert coherence_gap([], total) == 0.0


def _diverging_run() -> tuple[list[float], dict[str, list[float]]]:
    """Two segments pulling in opposite directions under a near-flat total."""
    t = np.arange(HISTORY)
    growing = 1000 + 60 * t
    shrinking = 3000 - 55 * t
    total = growing + shrinking
    return [float(v) for v in total], {
        "Growing": [float(v) for v in growing],
        "Shrinking": [float(v) for v in shrinking],
    }


def _run_with_segments():
    total, parts = _diverging_run()
    history = periods(HISTORY)

    segments = [
        SegmentInput(
            label=label,
            current_total=float(sum(values[-12:])),
            prior_total=float(sum(values[-24:-12])),
            series=values[-12:],
            periods=history,
            values=values,
        )
        for label, values in parts.items()
    ]

    return run_forecast(
        ForecastInput(
            series=SeriesInput(periods=history, values=total),
            frequency=MONTHLY,
            horizon=HORIZON,
            regions=segments,
        )
    )


def test_segments_move_apart_when_the_data_says_they_do() -> None:
    output = _run_with_segments()
    by_label = {row.label: row for row in output.regions}

    assert set(by_label) == {"Growing", "Shrinking"}

    growing_change = by_label["Growing"].change_vs_last_year
    shrinking_change = by_label["Shrinking"].change_vs_last_year
    assert growing_change is not None and growing_change > 0
    assert shrinking_change is not None and shrinking_change < 0

    # The split is no longer frozen: the growing segment must take a larger
    # share of the forecast than it held over the last year.
    assert by_label["Growing"].share > 25.0


def test_each_segment_reports_its_own_measured_accuracy() -> None:
    output = _run_with_segments()

    assert output.regions, "the run produced no segments"
    for row in output.regions:
        assert row.accuracy_measured, f"{row.label} inherited the top line's accuracy"
        assert row.model is not None, f"{row.label} did not name the model that forecast it"
        assert row.accuracy is not None


def test_the_segments_still_add_up_to_the_headline() -> None:
    output = _run_with_segments()

    total = float(np.sum(output.point_forecast))
    assert sum(row.forecast_value for row in output.regions) == pytest.approx(total, rel=1e-6)
    assert sum(row.share for row in output.regions) == pytest.approx(100.0, abs=0.1)


def test_a_segment_too_short_to_backtest_is_marked_estimated() -> None:
    total, _parts = _diverging_run()
    history = periods(HISTORY)

    # Three points is nowhere near enough to validate a model.
    stub = SegmentInput(
        label="Brand new",
        current_total=300.0,
        prior_total=None,
        series=[100.0, 100.0, 100.0],
        periods=history[-3:],
        values=[100.0, 100.0, 100.0],
    )

    output = run_forecast(
        ForecastInput(
            series=SeriesInput(periods=history, values=total),
            frequency=MONTHLY,
            horizon=HORIZON,
            regions=[stub],
        )
    )

    row = next(r for r in output.regions if r.label == "Brand new")
    assert row.accuracy_measured is False
    assert row.model is None
    assert row.forecast_value > 0, "an estimated segment still gets a number"


def test_no_segments_is_not_an_error() -> None:
    total, _parts = _diverging_run()
    output = run_forecast(
        ForecastInput(
            series=SeriesInput(periods=periods(HISTORY), values=total),
            frequency=MONTHLY,
            horizon=HORIZON,
        )
    )

    assert output.regions == []
    assert output.categories == []


# ---------------------------------------------------------------- the tree


def _leaf(region: str, sku: str, forecast: list[float], share: float):
    return ({"region": region, "sku": sku}, f"{region} · {sku}", np.array(forecast), share)


def test_the_tree_grows_the_levels_the_grouping_implies() -> None:
    root = build_tree(
        [
            _leaf("North", "A", [10.0], 0.4),
            _leaf("North", "B", [10.0], 0.2),
            _leaf("South", "A", [10.0], 0.4),
        ],
        ["region", "sku"],
    )

    assert root.level == 0
    assert {child.label for child in root.children} == {"North", "South"}

    north = next(c for c in root.children if c.label == "North")
    assert north.level == 1
    assert {c.label for c in north.children} == {"North · A", "North · B"}
    assert north.share == pytest.approx(0.6), "a parent's share is its children's"

    assert len(list(walk(root))) == 6


def test_every_level_adds_up_after_reconciliation() -> None:
    root = build_tree(
        [
            _leaf("North", "A", [40.0, 40.0], 0.4),
            _leaf("North", "B", [20.0, 20.0], 0.2),
            _leaf("South", "A", [40.0, 40.0], 0.4),
        ],
        ["region", "sku"],
    )
    total = np.array([200.0, 240.0])

    reconcile_tree(root, total)

    assert np.allclose(root.reconciled, total)

    regions = [c.reconciled for c in root.children]
    assert np.allclose(bottom_up(regions), total), "regions must sum to the total"

    leaves = [n.reconciled for n in walk(root) if n.is_leaf]
    assert np.allclose(bottom_up(leaves), total), "leaves must sum to the total"

    for parent in root.children:
        children = [c.reconciled for c in parent.children]
        assert np.allclose(bottom_up(children), parent.reconciled), f"{parent.label} does not close"


def test_a_child_keeps_its_own_direction_inside_its_parent() -> None:
    root = build_tree(
        [
            _leaf("North", "Rising", [10.0, 90.0], 0.25),
            _leaf("North", "Falling", [90.0, 10.0], 0.25),
            _leaf("South", "Flat", [50.0, 50.0], 0.5),
        ],
        ["region", "sku"],
    )

    reconcile_tree(root, np.array([200.0, 200.0]))

    north = next(c for c in root.children if c.label == "North")
    rising = next(c for c in north.children if c.label.endswith("Rising"))
    falling = next(c for c in north.children if c.label.endswith("Falling"))

    assert rising.reconciled[0] < rising.reconciled[1]
    assert falling.reconciled[0] > falling.reconciled[1]


def test_grouped_forecasting_measures_every_leaf_it_can() -> None:
    from app.forecasting.engine import SegmentInput, forecast_grouped

    history = periods(HISTORY)
    t = np.arange(HISTORY)

    leaves = []
    for region, slope in (("North", 40.0), ("South", -30.0)):
        for sku, base in (("A", 1200.0), ("B", 900.0)):
            values = base + slope * t + 80 * np.sin(2 * np.pi * t / 12)
            leaves.append(
                SegmentInput(
                    label=f"{region} · {sku}",
                    current_total=float(np.sum(values[-12:])),
                    prior_total=float(np.sum(values[-24:-12])),
                    series=[float(v) for v in values[-12:]],
                    periods=history,
                    values=[float(v) for v in values],
                    key={"region": region, "sku": sku},
                )
            )

    total = np.asarray([sum(leaf.values[i] for leaf in leaves) for i in range(HISTORY)])
    total_path = np.full(HORIZON, float(np.mean(total[-6:])))

    results = forecast_grouped(leaves, ["region", "sku"], total_path, MONTHLY, HORIZON, None)

    levels = {row.level for row in results}
    assert levels == {0, 1, 2}, "total, regions and leaves must all be present"

    leaf_rows = [row for row in results if row.level == 2]
    assert len(leaf_rows) == 4
    assert all(row.accuracy_measured for row in leaf_rows)
    assert all(row.model is not None for row in leaf_rows)

    # Each level closes on the same number.
    root = next(row for row in results if row.level == 0)
    assert sum(r.forecast_total for r in results if r.level == 1) == pytest.approx(
        root.forecast_total, rel=1e-6
    )
    assert sum(r.forecast_total for r in leaf_rows) == pytest.approx(root.forecast_total, rel=1e-6)


def test_a_leaf_that_cannot_be_validated_is_apportioned_and_says_so() -> None:
    from app.forecasting.engine import SegmentInput, forecast_grouped
    from app.models.enums import SeriesStatus

    history = periods(HISTORY)
    t = np.arange(HISTORY)
    solid = 1000 + 20 * t

    leaves = [
        SegmentInput(
            label="Established",
            current_total=float(np.sum(solid[-12:])),
            prior_total=float(np.sum(solid[-24:-12])),
            series=[float(v) for v in solid[-12:]],
            periods=history,
            values=[float(v) for v in solid],
            key={"sku": "Established"},
        ),
        SegmentInput(
            label="Brand new",
            current_total=300.0,
            prior_total=None,
            series=[100.0] * 3,
            periods=history[-3:],
            values=[100.0, 100.0, 100.0],
            key={"sku": "Brand new"},
        ),
    ]

    total_path = np.full(HORIZON, 1500.0)
    results = forecast_grouped(leaves, ["sku"], total_path, MONTHLY, HORIZON, None)

    new = next(row for row in results if row.label == "Brand new")
    assert new.accuracy_measured is False
    assert new.model is None
    assert new.status is SeriesStatus.ESTIMATED
    assert new.blocked_reason
    assert new.forecast_total > 0, "an unvalidated leaf still gets a number"

    root = next(row for row in results if row.level == 0)
    assert sum(r.forecast_total for r in results if r.level == 1) == pytest.approx(
        root.forecast_total, rel=1e-6
    )


def test_grouping_by_nothing_returns_nothing() -> None:
    from app.forecasting.engine import forecast_grouped

    assert forecast_grouped([], ["sku"], np.zeros(3), MONTHLY, 3, None) == []


def test_a_series_carries_a_band_its_own_backtest_earned() -> None:
    from app.forecasting.engine import SegmentInput, forecast_grouped

    history = periods(HISTORY)
    t = np.arange(HISTORY)

    leaves = [
        SegmentInput(
            label=f"{region} · A",
            current_total=float(np.sum((base + 30 * t)[-12:])),
            prior_total=float(np.sum((base + 30 * t)[-24:-12])),
            series=[float(v) for v in (base + 30 * t)[-12:]],
            periods=history,
            values=[float(v) for v in base + 30 * t + 60 * np.sin(2 * np.pi * t / 12)],
            key={"region": region},
        )
        for region, base in (("North", 1200.0), ("South", 800.0))
    ]

    total_path = np.full(HORIZON, 4000.0)
    results = forecast_grouped(leaves, ["region"], total_path, MONTHLY, HORIZON, None, 0.8)

    for row in results:
        if not row.accuracy_measured:
            continue

        assert len(row.lower) == len(row.forecast) == len(row.upper), row.label
        # The band brackets the line it belongs to, at the reconciled height —
        # left unscaled it would sit beside the series rather than around it.
        for low, point, high in zip(row.lower, row.forecast, row.upper, strict=True):
            assert low <= point <= high, f"{row.label} band does not contain its own forecast"


def test_an_apportioned_series_gets_no_band_at_all() -> None:
    from app.forecasting.engine import SegmentInput, forecast_grouped

    history = periods(HISTORY)
    solid = 1000 + 20 * np.arange(HISTORY)

    leaves = [
        SegmentInput(
            label="Established",
            current_total=float(np.sum(solid[-12:])),
            prior_total=float(np.sum(solid[-24:-12])),
            series=[float(v) for v in solid[-12:]],
            periods=history,
            values=[float(v) for v in solid],
            key={"sku": "Established"},
        ),
        SegmentInput(
            label="Brand new",
            current_total=300.0,
            prior_total=None,
            series=[100.0] * 3,
            periods=history[-3:],
            values=[100.0, 100.0, 100.0],
            key={"sku": "Brand new"},
        ),
    ]

    results = forecast_grouped(
        leaves, ["sku"], np.full(HORIZON, 1500.0), MONTHLY, HORIZON, None, 0.8
    )

    new = next(row for row in results if row.label == "Brand new")
    # An inherited band would claim a precision this series never demonstrated.
    assert new.lower == [] and new.upper == []
    assert new.forecast_total > 0
