from __future__ import annotations

from datetime import date

import numpy as np

from app.datasets.quality import (
    build_report,
    expected_periods,
    regularise,
    resolve_fill,
    winsorise,
)
from app.models.enums import ForecastFrequency, GapFill, IssueSeverity

MONTHLY = ForecastFrequency.MONTHLY
DAILY = ForecastFrequency.DAILY


def months(n: int, start: date = date(2022, 1, 1)) -> list[date]:
    from app.forecasting.frequency import add_periods

    return [add_periods(start, i, MONTHLY) for i in range(n)]


def report_for(periods, values, *, fill=GapFill.AUTO, row_counts=None, duplicates=0):
    return build_report(
        rows_scanned=len(values),
        rows_usable=len(values),
        duplicate_rows=duplicates,
        row_counts=row_counts if row_counts is not None else [10] * len(values),
        periods=periods,
        values=values,
        frequency=MONTHLY,
        fill=fill,
    )


def test_expected_periods_walks_the_calendar_per_frequency() -> None:
    assert expected_periods(date(2024, 1, 1), date(2024, 4, 1), MONTHLY) == [
        date(2024, 1, 1),
        date(2024, 2, 1),
        date(2024, 3, 1),
        date(2024, 4, 1),
    ]
    assert len(expected_periods(date(2024, 1, 1), date(2024, 1, 10), DAILY)) == 10


def test_a_complete_series_is_left_alone() -> None:
    periods = months(12)
    values = [float(i) for i in range(12)]

    out_periods, out_values, _weights, applied, missing = regularise(periods, values, None, MONTHLY)

    assert out_periods == periods
    assert out_values == values
    assert applied is GapFill.NONE
    assert missing == []


def test_gaps_are_reindexed_onto_the_full_calendar() -> None:
    periods = months(12)
    values = [100.0 + 10 * i for i in range(12)]

    keep = [i for i in range(12) if i not in (3, 4, 9)]
    gappy_periods = [periods[i] for i in keep]
    gappy_values = [values[i] for i in keep]

    out_periods, out_values, _w, applied, missing = regularise(
        gappy_periods, gappy_values, None, MONTHLY
    )

    assert out_periods == periods, "the calendar must be complete again"
    assert len(out_values) == 12
    assert len(missing) == 3
    assert applied is GapFill.INTERPOLATE
    assert out_values[3] == 130.0 and out_values[4] == 140.0, "interpolated across the hole"


def test_intermittent_gaps_are_filled_with_zero_not_interpolated() -> None:
    values = [0.0, 0.0, 40.0, 0.0, 0.0, 60.0, 0.0, 0.0]
    assert resolve_fill(values, GapFill.AUTO) is GapFill.ZERO

    smooth = [100.0, 105.0, 103.0, 110.0]
    assert resolve_fill(smooth, GapFill.AUTO) is GapFill.INTERPOLATE


def test_an_explicit_fill_choice_overrides_the_automatic_one() -> None:
    periods = months(6)
    values = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    keep = [0, 1, 3, 4, 5]

    _p, filled, _w, applied, _m = regularise(
        [periods[i] for i in keep], [values[i] for i in keep], None, MONTHLY, GapFill.ZERO
    )

    assert applied is GapFill.ZERO
    assert filled[2] == 0.0


def test_weights_follow_the_reindexed_calendar() -> None:
    periods = months(5)
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    weights = [10.0, 20.0, 30.0, 40.0, 50.0]
    keep = [0, 1, 3, 4]

    _p, out_values, out_weights, _a, _m = regularise(
        [periods[i] for i in keep],
        [values[i] for i in keep],
        [weights[i] for i in keep],
        MONTHLY,
    )

    assert out_weights is not None
    assert len(out_weights) == len(out_values) == 5
    assert out_weights[2] == 0.0, "a filled period carries no weight of its own"


def test_report_counts_gaps_and_coverage() -> None:
    periods = months(12)
    keep = [i for i in range(12) if i not in (2, 3, 4, 8)]

    report = report_for([periods[i] for i in keep], [float(i) for i in keep])

    assert report.gap_count == 4
    assert report.periods_expected == 12
    assert report.longest_gap == 3
    assert 0.6 < report.coverage < 0.7
    assert any(issue.code == "calendar_gaps" for issue in report.issues)


def test_severe_gaps_block_the_run_but_mild_ones_only_warn() -> None:
    periods = months(24)

    mild = report_for(
        [periods[i] for i in range(24) if i != 5],
        [float(i) for i in range(24) if i != 5],
    )
    assert not mild.blocked

    keep = list(range(0, 24, 4))
    severe = report_for([periods[i] for i in keep], [float(i) for i in keep])
    assert severe.blocked


def test_a_constant_target_is_reported_but_not_refused() -> None:
    """A discontinued line is the same value in every period, and the flat
    forecast is the right answer for it. What cannot be done is measure that
    forecast — every percentage error divides by a total that never moves."""
    report = report_for(months(12), [42.0] * 12)

    assert report.constant_target
    assert not report.blocked
    assert any(issue.code == "constant_target" for issue in report.issues)


def test_a_single_period_cannot_be_forecast() -> None:
    report = report_for(months(1), [10.0])
    assert report.blocked


def test_duplicates_and_partial_periods_are_reported_without_blocking() -> None:
    periods = months(12)
    values = [100.0 + i for i in range(12)]
    counts = [30] * 11 + [2]

    report = report_for(periods, values, row_counts=counts, duplicates=44)

    assert report.duplicate_rows == 44
    assert report.partial_periods == 1
    assert not report.blocked

    codes = {issue.code: issue.severity for issue in report.issues}
    assert codes["duplicate_timestamps"] is IssueSeverity.INFO
    assert codes["partial_periods"] is IssueSeverity.WARNING


def test_outliers_and_negatives_are_surfaced() -> None:
    values = [100.0] * 20
    values[10] = 5_000.0
    values[15] = -80.0

    report = report_for(months(20), values)

    assert report.outlier_periods >= 1
    assert report.negative_periods == 1
    assert not report.blocked


def test_winsorise_damps_a_spike_without_moving_the_rest() -> None:
    values = [100.0, 102.0, 98.0, 101.0, 5_000.0, 99.0, 103.0]
    treated = winsorise(values)

    assert treated[4] < 1_000.0
    assert treated[:4] == values[:4]
    assert max(treated) < max(values)


def test_winsorise_leaves_a_short_series_untouched() -> None:
    values = [1.0, 900.0, 2.0]
    assert winsorise(values) == values


def test_report_survives_an_empty_series() -> None:
    report = build_report(
        rows_scanned=120,
        rows_usable=0,
        duplicate_rows=0,
        row_counts=[],
        periods=[],
        values=[],
        frequency=MONTHLY,
        fill=GapFill.AUTO,
    )

    assert report.blocked
    assert report.coverage == 0.0
    assert any(issue.code == "no_usable_rows" for issue in report.issues)


def test_report_serialises_for_the_api() -> None:
    payload = report_for(months(12), [float(i) for i in range(12)]).as_dict()

    assert payload["periods_expected"] == 12
    assert isinstance(payload["issues"], list)
    assert set(payload) >= {"coverage", "gap_count", "blocked", "fill_applied"}
    assert np.isfinite(payload["coverage"])
