from __future__ import annotations

import numpy as np
import pytest

from app.forecasting.calibration import (
    COVERAGE_TOLERANCE_PP,
    MIN_COVERAGE_SAMPLE,
    HeldOutPoint,
    Interval,
    apply_halfwidths,
    calibrate,
    conformal_halfwidths,
    gaussian_halfwidths,
    is_monotone_in_horizon,
    measure_coverage,
    realised_coverage,
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


class TestCoverageOfIntervalsThatWereActuallyServed:
    def test_it_counts_what_landed_inside_the_published_band(self) -> None:
        intervals = [
            Interval(horizon=1, actual=value, lower=90.0, upper=110.0)
            for value in [*([100.0] * 8), *([200.0] * 2)]
        ]

        report = realised_coverage(intervals, nominal=0.8)

        assert [point.observed for point in report.points] == [0.8]
        assert report.points[0].n_observations == 10
        assert report.holds

    def test_a_band_that_is_not_centred_is_still_measured_honestly(self) -> None:
        inside = Interval(horizon=1, actual=118.0, lower=95.0, upper=120.0)
        outside = Interval(horizon=1, actual=94.0, lower=95.0, upper=120.0)

        report = realised_coverage([inside] * 9 + [outside], nominal=0.9)

        assert report.points[0].observed == pytest.approx(0.9)
        assert report.holds

    def test_an_endpoint_counts_as_inside(self) -> None:
        report = realised_coverage(
            [Interval(horizon=1, actual=110.0, lower=90.0, upper=110.0)], nominal=0.8
        )

        assert report.points[0].observed == 1.0

    def test_a_missing_bound_is_dropped_rather_than_counted_as_a_miss(self) -> None:
        usable = [Interval(horizon=1, actual=100.0, lower=90.0, upper=110.0)] * 4
        broken = [Interval(horizon=1, actual=100.0, lower=float("nan"), upper=110.0)] * 4

        report = realised_coverage([*usable, *broken], nominal=0.8)

        assert report.points[0].n_observations == 4
        assert report.points[0].observed == 1.0

    def test_horizons_are_reported_separately_and_in_order(self) -> None:
        intervals = [
            Interval(horizon=horizon, actual=100.0, lower=99.0, upper=101.0)
            for horizon in (3, 1, 2, 1)
        ]

        report = realised_coverage(intervals, nominal=0.8)

        assert [point.horizon for point in report.points] == [1, 2, 3]
        assert [point.n_observations for point in report.points] == [2, 1, 1]

    def test_a_band_narrower_than_it_claims_fails_the_promise(self) -> None:
        misses = [Interval(horizon=1, actual=500.0, lower=90.0, upper=110.0)] * 5
        hits = [Interval(horizon=1, actual=100.0, lower=90.0, upper=110.0)] * 5

        report = realised_coverage([*misses, *hits], nominal=0.8)

        assert not report.holds
        assert report.worst_gap_pp == pytest.approx(-30.0)


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


class TestScoringAnIntervalCannotReadTheFuture:
    @staticmethod
    def _fold(index: int, error: float):
        from app.forecasting.backtest import FoldResult

        return FoldResult(
            fold=index,
            train_size=10 + 3 * index,
            test_size=3,
            y_true=[10.0, 10.0, 10.0],
            y_pred=[10.0 + error, 10.0 - error, 10.0 + error],
            y_step=[1, 2, 3],
        )

    def test_the_first_fold_is_not_scored_against_what_came_after_it(self) -> None:
        import numpy as np

        from app.forecasting.backtest import (
            BacktestResult,
            interval_cost,
            normal_quantile,
        )
        from app.forecasting.metrics import winkler
        from app.models.enums import ModelKind

        quiet, loud = self._fold(0, 0.1), self._fold(1, 5.0)
        result = BacktestResult(model=ModelKind.NAIVE, folds=[quiet, loud])

        z = normal_quantile(0.8)
        sigma = float(
            np.std(
                np.asarray(
                    [t - p for t, p in zip(quiet.y_true, quiet.y_pred, strict=True)], dtype=float
                )
            )
        )
        predicted = np.asarray(loud.y_pred, dtype=float)
        only_honest_score = winkler(
            np.asarray(loud.y_true, dtype=float),
            predicted - z * sigma,
            predicted + z * sigma,
            0.8,
        )

        assert interval_cost(result, 0.8) == pytest.approx(only_honest_score)

    def test_a_later_fold_cannot_change_an_earlier_folds_width(self) -> None:
        import numpy as np

        from app.forecasting.backtest import BacktestResult, interval_cost
        from app.models.enums import ModelKind

        def scored(last_error: float) -> float:
            folds = [self._fold(0, 0.1), self._fold(1, 0.2), self._fold(2, last_error)]
            return interval_cost(BacktestResult(model=ModelKind.NAIVE, folds=folds), 0.8)

        calm, wild = scored(0.3), scored(80.0)
        assert np.isfinite(calm) and np.isfinite(wild)

        pair = [self._fold(0, 0.1), self._fold(1, 0.2)]
        fold_one_term = interval_cost(BacktestResult(model=ModelKind.NAIVE, folds=pair), 0.8)

        for total, last in ((calm, 0.3), (wild, 80.0)):
            fold_two_term = 2.0 * total - fold_one_term
            assert fold_two_term > 0.0, (last, total, fold_one_term)
            assert total == pytest.approx((fold_one_term + fold_two_term) / 2.0)


class TestABandIsAsWideAsItClaims:
    HORIZON = 12
    STEP_SIGMA = 10.0

    def _truth(self) -> np.ndarray:
        return self.STEP_SIGMA * np.sqrt(np.arange(1, self.HORIZON + 1))

    def _backtest(self, folds: int, rng: np.random.Generator):
        from app.forecasting.backtest import BacktestResult, FoldResult
        from app.models.enums import ModelKind

        truth = self._truth()
        return BacktestResult(
            model=ModelKind.NAIVE,
            folds=[
                FoldResult(
                    fold=index,
                    train_size=80,
                    test_size=self.HORIZON,
                    y_true=[float(v) for v in rng.normal(0, 1, self.HORIZON) * truth],
                    y_pred=[0.0] * self.HORIZON,
                    y_step=list(range(1, self.HORIZON + 1)),
                )
                for index in range(folds)
            ],
        )

    def _coverage(self, folds: int, seed: int = 11) -> float:
        from app.forecasting.scenarios import build_intervals

        rng = np.random.default_rng(seed)
        truth = self._truth()
        history = np.cumsum(rng.normal(0, self.STEP_SIGMA, 80))

        inside = total = 0
        for _ in range(400):
            bands = build_intervals(
                np.zeros(self.HORIZON), self._backtest(folds, rng), 0.8, history=history
            )
            fresh = rng.normal(0, 1, self.HORIZON) * truth
            inside += int(((fresh >= bands.lower) & (fresh <= bands.upper)).sum())
            total += self.HORIZON
        return 100.0 * inside / total

    @pytest.mark.parametrize("folds", [2, 3, 5, 8])
    def test_coverage_lands_near_the_level_it_claims(self, folds: int) -> None:
        observed = self._coverage(folds)
        assert 74.0 <= observed <= 88.0, f"{folds} folds covered {observed:.1f}% of an 80% band"

    def test_more_folds_do_not_make_it_worse(self) -> None:
        assert abs(self._coverage(8, seed=3) - 80.0) <= abs(self._coverage(3, seed=3) - 80.0) + 4.0

    @pytest.mark.parametrize("folds", [3, 8])
    def test_the_band_never_narrows_as_the_horizon_grows(self, folds: int) -> None:
        from app.forecasting.scenarios import build_intervals

        rng = np.random.default_rng(5)
        history = np.cumsum(rng.normal(0, self.STEP_SIGMA, 80))
        for _ in range(50):
            bands = build_intervals(
                np.zeros(self.HORIZON), self._backtest(folds, rng), 0.8, history=history
            )
            width = bands.upper - bands.lower
            assert np.all(np.diff(width) >= -1e-9), width


def test_a_non_negative_metric_never_publishes_an_inverted_band() -> None:
    from app.forecasting.backtest import BacktestResult, FoldResult
    from app.forecasting.scenarios import build_intervals
    from app.models.enums import ModelKind

    horizon = 6
    rng = np.random.default_rng(3)
    backtest = BacktestResult(
        model=ModelKind.NAIVE,
        folds=[
            FoldResult(
                fold=index,
                train_size=36,
                test_size=horizon,
                y_true=[float(v) for v in rng.normal(0, 12.0, horizon)],
                y_pred=[0.0] * horizon,
                y_step=list(range(1, horizon + 1)),
            )
            for index in range(5)
        ],
    )
    history = np.linspace(200.0, 10.0, 36)

    for level in (-5.0, -80.0, -400.0):
        point = np.full(horizon, level)
        bands = build_intervals(point, backtest, 0.8, history=history, non_negative=True)

        assert np.all(bands.lower >= 0.0), bands.lower
        assert np.all(bands.worst_case >= 0.0), bands.worst_case
        assert np.all(bands.upper >= bands.lower), (bands.lower, bands.upper)
        assert np.all(bands.best_case >= bands.upper), (bands.upper, bands.best_case)
        assert np.all(bands.worst_case <= bands.lower), (bands.worst_case, bands.lower)
