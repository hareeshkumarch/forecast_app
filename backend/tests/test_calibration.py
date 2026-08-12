from __future__ import annotations

import numpy as np
import pytest

from app.forecasting.calibration import (
    COVERAGE_TOLERANCE_PP,
    MIN_COVERAGE_SAMPLE,
    HeldOutPoint,
    apply_halfwidths,
    calibrate,
    conformal_halfwidths,
    gaussian_halfwidths,
    is_monotone_in_horizon,
    measure_coverage,
    widen_with_horizon,
)

LEVELS = (0.5, 0.8, 0.95)


def points_with_spread(
    horizons: int,
    per_horizon: int,
    spread: np.ndarray | float,
    seed: int = 7,
) -> list[HeldOutPoint]:
    rng = np.random.default_rng(seed)
    out: list[HeldOutPoint] = []
    for horizon in range(1, horizons + 1):
        sigma = spread[horizon - 1] if isinstance(spread, np.ndarray) else spread * horizon
        for _ in range(per_horizon):
            predicted = 100.0
            out.append(
                HeldOutPoint(
                    horizon=horizon,
                    predicted=predicted,
                    actual=predicted + float(rng.normal(0.0, sigma)),
                )
            )
    return out


class TestCoverageIsMeasured:
    def test_a_too_narrow_interval_is_reported_as_too_narrow(self) -> None:
        points = points_with_spread(horizons=3, per_horizon=200, spread=10.0)
        starved = {horizon: 0.5 * 1.2816 * 10.0 * horizon for horizon in (1, 2, 3)}

        report = measure_coverage(points, starved, nominal=0.8)

        assert report.measurable_points
        assert not report.holds
        assert report.worst_gap_pp < -COVERAGE_TOLERANCE_PP
        for point in report.points:
            assert point.observed < 0.8

    def test_coverage_is_reported_per_horizon_and_per_level(self) -> None:
        points = points_with_spread(horizons=4, per_horizon=120, spread=6.0)

        for nominal in LEVELS:
            report = measure_coverage(
                points, conformal_halfwidths(points, nominal), nominal=nominal
            )
            assert [p.horizon for p in report.points] == [1, 2, 3, 4]
            assert all(p.nominal == nominal for p in report.points)

    def test_a_sample_too_small_to_measure_says_so_instead_of_guessing(self) -> None:
        points = [
            HeldOutPoint(horizon=1, predicted=10.0, actual=10.0 + offset)
            for offset in range(MIN_COVERAGE_SAMPLE - 1)
        ]
        report = measure_coverage(points, {1: 2.0}, nominal=0.8)

        assert report.points
        assert report.measurable_points == []
        assert not report.holds
        assert np.isnan(report.worst_gap_pp)


class TestConformalRepairsCoverage:
    @pytest.mark.parametrize("nominal", LEVELS)
    def test_coverage_lands_within_tolerance_at_every_served_level(self, nominal: float) -> None:
        points = points_with_spread(horizons=5, per_horizon=200, spread=8.0)

        result = calibrate(points, nominal)

        assert result.after.measurable_points
        for point in result.after.points:
            assert abs(point.gap_pp) <= COVERAGE_TOLERANCE_PP, (
                f"{nominal:.0%} interval covered {point.observed:.1%} "
                f"at horizon {point.horizon}"
            )

    def test_it_repairs_an_overconfident_model_and_shows_the_gap_it_closed(self) -> None:
        points = points_with_spread(horizons=4, per_horizon=200, spread=9.0)
        overconfident = gaussian_halfwidths({h: 9.0 * h / 3.0 for h in (1, 2, 3, 4)}, 0.8)

        result = calibrate(points, 0.8, model_halfwidths=overconfident)

        assert not result.before.holds
        assert result.before.worst_gap_pp < -COVERAGE_TOLERANCE_PP
        assert result.after.holds
        assert result.improved

    def test_conformal_does_not_assume_normal_errors(self) -> None:
        rng = np.random.default_rng(3)
        points = [
            HeldOutPoint(horizon=1, predicted=50.0, actual=50.0 + float(rng.standard_t(2.5)) * 4.0)
            for _ in range(600)
        ]

        result = calibrate(points, 0.8)

        assert abs(result.after.points[0].gap_pp) <= COVERAGE_TOLERANCE_PP


class TestIntervalsWidenWithHorizon:
    def test_served_intervals_never_narrow_as_the_horizon_grows(self) -> None:
        points = points_with_spread(horizons=6, per_horizon=150, spread=5.0)

        halfwidths = conformal_halfwidths(points, 0.8)

        assert is_monotone_in_horizon(halfwidths)
        assert halfwidths[6] > halfwidths[1]

    def test_a_sample_that_narrows_is_carried_forward_instead_of_believed(self) -> None:
        noisy = np.array([2.0, 9.0, 3.0, 4.0])
        points = points_with_spread(horizons=4, per_horizon=120, spread=noisy)

        raw = conformal_halfwidths(points, 0.8, enforce_monotone=False)
        served = conformal_halfwidths(points, 0.8)

        assert not is_monotone_in_horizon(raw)
        assert is_monotone_in_horizon(served)
        assert served[3] == served[2]

    def test_widening_leaves_an_already_monotone_run_alone(self) -> None:
        widths = {1: 1.0, 2: 2.0, 3: 5.0}
        assert widen_with_horizon(widths) == widths


class TestServedBounds:
    def test_bounds_are_centred_on_the_point_forecast(self) -> None:
        lower, upper = apply_halfwidths([10.0, 20.0], [1, 2], {1: 1.5, 2: 4.0})

        assert lower == [8.5, 16.0]
        assert upper == [11.5, 24.0]

    def test_an_unseen_horizon_gets_the_widest_width_rather_than_none(self) -> None:
        lower, upper = apply_halfwidths([10.0], [9], {1: 1.0, 2: 3.0})

        assert lower == [7.0]
        assert upper == [13.0]

    def test_it_refuses_mismatched_inputs(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            apply_halfwidths([1.0, 2.0], [1], {1: 1.0})


class TestReportIsTraceable:
    def test_the_report_carries_the_evidence_behind_each_figure(self) -> None:
        points = points_with_spread(horizons=3, per_horizon=100, spread=7.0)

        payload = calibrate(points, 0.8, model_halfwidths={1: 1.0, 2: 1.0, 3: 1.0}).as_dict()

        assert payload["nominal"] == 0.8
        assert payload["holds"] is True
        assert set(payload["halfwidths"]) == {"1", "2", "3"}
        before = payload["coverage_before"]
        assert isinstance(before, list)
        assert all({"observed", "gap_pp", "n_observations"} <= set(row) for row in before)
        assert payload["worst_gap_before_pp"] is not None
        assert payload["worst_gap_before_pp"] < payload["worst_gap_after_pp"]
