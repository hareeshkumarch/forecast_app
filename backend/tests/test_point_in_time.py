from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.forecasting.features import FeatureSpec, build_design_matrix, build_future_row
from app.models.enums import ForecastFrequency

WEEKLY = ForecastFrequency.WEEKLY


def weeks(count: int, start: date = date(2023, 1, 2)) -> list[date]:
    return [start + timedelta(weeks=index) for index in range(count)]


def series(count: int, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    trend = np.linspace(50.0, 90.0, count)
    season = 8.0 * np.sin(np.arange(count) * 2.0 * np.pi / 52.0)
    return trend + season + rng.normal(0.0, 3.0, size=count)


def spec() -> FeatureSpec:
    return FeatureSpec(
        lags=[1, 2, 4, 52],
        rolling_windows=[4, 13],
        seasonal_period=52,
    )


class TestReplayIsIdentical:
    @pytest.mark.parametrize("as_of", [80, 120, 160])
    def test_appending_later_data_does_not_change_the_frame_built_before_it(
        self, as_of: int
    ) -> None:
        full = series(200)
        periods = weeks(200)

        at_the_time, y_then, names_then, rows_then = build_design_matrix(
            full[:as_of], periods[:as_of], spec(), WEEKLY
        )
        with_hindsight, y_now, names_now, rows_now = build_design_matrix(
            full[:as_of], periods[:as_of], spec(), WEEKLY
        )

        assert names_then == names_now
        assert rows_then == rows_now
        np.testing.assert_array_equal(at_the_time, with_hindsight)
        np.testing.assert_array_equal(y_then, y_now)

    @pytest.mark.parametrize("as_of", [120, 160])
    def test_the_rows_that_existed_at_as_of_are_untouched_by_what_came_after(
        self, as_of: int
    ) -> None:
        full = series(200)
        periods = weeks(200)

        early, y_early, names_early, rows_early = build_design_matrix(
            full[:as_of], periods[:as_of], spec(), WEEKLY
        )
        late, y_late, names_late, rows_late = build_design_matrix(full, periods, spec(), WEEKLY)

        shared = sorted(set(names_early) & set(names_late))
        assert shared, "the two frames have no column in common"

        overlap = len(rows_early)
        assert rows_late[:overlap] == rows_early

        for name in shared:
            np.testing.assert_allclose(
                late[:overlap, names_late.index(name)],
                early[:, names_early.index(name)],
                rtol=0,
                atol=0,
                err_msg=f"{name} changed once later periods existed",
            )
        np.testing.assert_allclose(y_late[:overlap], y_early, rtol=0, atol=0)

    def test_a_longer_history_only_ever_adds_columns(self) -> None:
        full = series(200)
        periods = weeks(200)

        _m, _y, short_names, _r = build_design_matrix(full[:120], periods[:120], spec(), WEEKLY)
        _m2, _y2, long_names, _r2 = build_design_matrix(full, periods, spec(), WEEKLY)

        assert set(short_names) <= set(long_names)


class TestRollingWindowsAreClosedOnTheLeft:
    def test_a_rolling_feature_never_contains_the_period_it_describes(self) -> None:
        n = 120
        values = np.concatenate([np.full(60, 10.0), np.full(60, 1000.0)])
        periods = weeks(n)

        matrix, _y, names, rows = build_design_matrix(
            values,
            periods,
            FeatureSpec(
                lags=[1],
                rolling_windows=[4],
                use_calendar=False,
                use_seasonal=False,
                use_trend=False,
            ),
            WEEKLY,
        )

        rolling = [index for index, name in enumerate(names) if name.startswith("roll_")]
        assert rolling, f"no rolling feature among {names}"

        step_row = rows.index(60)
        before_row = rows.index(59)

        mean_column = names.index("roll_mean_4")
        assert matrix[step_row, mean_column] == pytest.approx(10.0), (
            "roll_mean_4 already knew about the step at the period it happened"
        )

        for column in rolling:
            assert matrix[step_row, column] == pytest.approx(matrix[before_row, column]), (
                f"{names[column]} moved on the period the step happened"
            )

    def test_the_step_does_become_visible_one_period_later(self) -> None:
        values = np.concatenate([np.full(60, 10.0), np.full(60, 1000.0)])

        matrix, _y, names, rows = build_design_matrix(
            values,
            weeks(120),
            FeatureSpec(
                lags=[1],
                rolling_windows=[4],
                use_calendar=False,
                use_seasonal=False,
                use_trend=False,
            ),
            WEEKLY,
        )

        mean_column = names.index("roll_mean_4")
        assert matrix[rows.index(61), mean_column] > 10.0


class TestNoWallClockInFeatureLogic:
    def test_the_same_history_gives_the_same_features_whenever_it_is_built(self) -> None:
        values = series(150)
        periods = weeks(150)

        frames = [build_design_matrix(values, periods, spec(), WEEKLY)[0] for _ in range(3)]

        for frame in frames[1:]:
            np.testing.assert_array_equal(frame, frames[0])


class TestTheFutureRowSeesOnlyHistory:
    def test_the_row_for_the_next_period_is_unchanged_by_what_actually_happens(self) -> None:
        full = series(160)
        periods = weeks(161)
        cut = 150

        built = spec()
        build_design_matrix(full[:cut], periods[:cut], built, WEEKLY)

        from_history = build_future_row(
            full[:cut], periods[:cut], periods[cut], built, WEEKLY
        )
        again = build_future_row(full[:cut], periods[:cut], periods[cut], built, WEEKLY)

        np.testing.assert_array_equal(from_history, again)
        assert np.isfinite(from_history).any()
