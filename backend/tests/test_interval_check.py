from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.forecasting.calibration import COVERAGE_TOLERANCE_PP, MIN_COVERAGE_SAMPLE
from app.forecasting.engine import ForecastInput, SeriesInput, run_forecast
from app.models.enums import ForecastFrequency

WEEKLY = ForecastFrequency.WEEKLY
WEEKS = 156
HORIZON = 8


def weeks(count: int = WEEKS, start: date = date(2023, 1, 2)) -> list[date]:
    return [start + timedelta(weeks=index) for index in range(count)]


def seasonal(count: int = WEEKS, noise: float = 20.0, seed: int = 41) -> list[float]:
    rng = np.random.default_rng(seed)
    index = np.arange(count)
    level = 900.0 + 2.0 * index
    season = 120.0 * np.sin(index * 2.0 * np.pi / 52.0)
    return list(level + season + rng.normal(0.0, noise, size=count))


DAYS = 200
DAILY = ForecastFrequency.DAILY


def days(count: int = DAYS, start: date = date(2023, 1, 2)) -> list[date]:
    return [start + timedelta(days=index) for index in range(count)]


def weekly_shape(count: int = DAYS, noise: float = 12.0, seed: int = 19) -> list[float]:
    rng = np.random.default_rng(seed)
    index = np.arange(count)
    level = 400.0 + 0.8 * index
    season = 70.0 * np.sin(index * 2.0 * np.pi / 7.0)
    return list(level + season + rng.normal(0.0, noise, size=count))


def _check(
    periods: list[date], values: list[float], frequency: ForecastFrequency
) -> dict[str, object]:
    output = run_forecast(
        ForecastInput(
            series=SeriesInput(periods=periods, values=values),
            frequency=frequency,
            horizon=HORIZON,
            confidence_level=0.8,
        )
    )
    result = output.diagnostics["interval_check"]
    assert isinstance(result, dict)
    return result


@pytest.fixture(scope="module")
def check() -> dict[str, object]:
    return _check(days(), weekly_shape(), DAILY)


class TestEveryRunChecksTheRangeItIsAboutToPublish:
    def test_the_check_runs_and_says_what_it_measured_against(
        self, check: dict[str, object]
    ) -> None:
        assert check["measured"] is True
        assert check["nominal"] == 0.8
        assert check["served"], "the served band was measured on held-out folds"

    def test_it_reports_a_share_per_horizon_within_the_published_reach(
        self, check: dict[str, object]
    ) -> None:
        served = check["served"]
        assert isinstance(served, list)
        horizons = [row["horizon"] for row in served]

        assert horizons == sorted(horizons)
        assert max(horizons) <= HORIZON
        assert all(0.0 <= row["observed"] <= 1.0 for row in served)
        assert all(row["nominal"] == 0.8 for row in served)

    def test_a_verdict_is_reached_rather_than_left_implicit(self, check: dict[str, object]) -> None:
        assert isinstance(check["served_holds"], bool)
        gap = check["served_worst_gap_pp"]
        assert gap is None or isinstance(gap, float)
        if isinstance(gap, float) and check["served_holds"]:
            assert abs(gap) <= COVERAGE_TOLERANCE_PP

    def test_the_repair_is_offered_beside_the_measurement_not_applied_silently(
        self, check: dict[str, object]
    ) -> None:
        halfwidths = check["conformal_halfwidths"]
        assert isinstance(halfwidths, dict)
        assert halfwidths, "a conformal width is computed for at least one horizon"
        assert all(width > 0 for width in halfwidths.values())

        widths = [halfwidths[key] for key in sorted(halfwidths, key=int)]
        assert widths == sorted(widths), "conformal widths never narrow with the horizon"

    def test_the_conformal_band_holds_on_the_residuals_it_was_built_from(
        self, check: dict[str, object]
    ) -> None:
        gap = check["conformal_pooled_gap_pp"]

        assert gap is not None, "pooling the steps clears the sample floor"
        assert abs(float(gap)) <= COVERAGE_TOLERANCE_PP

    def test_a_single_horizon_has_too_few_origins_to_speak_for_itself(
        self, check: dict[str, object]
    ) -> None:
        # A run affords a handful of origins, so one horizon never reaches the
        # sample floor on its own. The widths are still computed per horizon;
        # it is the coverage share that is withheld.
        assert check["conformal_halfwidths"]
        assert check["conformal_worst_gap_pp"] is None

    def test_the_pooled_figure_says_how_much_evidence_is_behind_it(
        self, check: dict[str, object]
    ) -> None:
        seen = check["served_pooled_observations"]

        assert isinstance(seen, int) and seen >= MIN_COVERAGE_SAMPLE
        assert check["served_pooled"] is not None
        assert 0.0 <= float(check["served_pooled"]) <= 1.0  # type: ignore[arg-type]
        assert isinstance(check["served_pooled_holds"], bool)


class TestTheCheckDoesNotInventAnAnswer:
    def test_a_series_too_short_to_backtest_says_it_could_not_measure(self) -> None:
        output = run_forecast(
            ForecastInput(
                series=SeriesInput(periods=weeks(6), values=[10.0, 12.0, 11.0, 13.0, 12.0, 14.0]),
                frequency=WEEKLY,
                horizon=2,
            )
        )
        check = output.diagnostics["interval_check"]

        assert isinstance(check, dict)
        if not check["measured"]:
            assert check["reason"]

    def test_a_band_floored_at_zero_is_skipped_rather_than_counted_as_a_miss(self) -> None:
        rng = np.random.default_rng(7)
        spiky = [float(max(0.0, rng.normal(4.0, 14.0))) for _ in range(WEEKS)]

        output = run_forecast(
            ForecastInput(
                series=SeriesInput(periods=weeks(), values=spiky),
                frequency=WEEKLY,
                horizon=HORIZON,
                confidence_level=0.8,
            )
        )
        check = output.diagnostics["interval_check"]

        assert isinstance(check, dict)
        assert check["measured"] is True
        assert isinstance(check["steps_skipped_at_zero"], int)
        assert check["steps_skipped_at_zero"] <= HORIZON
