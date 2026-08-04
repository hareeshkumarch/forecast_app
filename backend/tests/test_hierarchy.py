from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.forecasting.engine import ForecastInput, SegmentInput, SeriesInput, run_forecast
from app.forecasting.frequency import add_periods
from app.forecasting.hierarchy import bottom_up, coherence_gap, reconcile_to_total
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
