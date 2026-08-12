"""Whether "about a minute" is still true.

The phrase sits on the homepage under the third step, so it is an SLO. The
failure mode it guards against is not a sudden one — it is a slightly better
candidate model, one more backtest fold, a richer feature set, each defensible
on its own, until the promise reads four minutes and nobody decided that.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import numpy as np
import pytest

from app.core.budget import (
    SERIES_CEILING,
    SERIES_HARD_LIMIT,
    STAGE_BUDGET_SECONDS,
    TOTAL_BUDGET_SECONDS,
    Admission,
    RunTimings,
    Stage,
    admission,
    percentile,
)
from app.forecasting.engine import ForecastInput, SeriesInput, run_forecast
from app.models.enums import ForecastFrequency

WEEKLY = ForecastFrequency.WEEKLY

#: The dataset the promise is made about: two years of weekly history, one
#: series, a nine-week horizon. Bigger than this is what the ceiling is for.
REFERENCE_WEEKS = 104
REFERENCE_HORIZON = 9
REFERENCE_RUNS = 5


def weeks(count: int = REFERENCE_WEEKS, start: date = date(2024, 1, 1)) -> list[date]:
    return [start + timedelta(weeks=index) for index in range(count)]


def reference_series(count: int = REFERENCE_WEEKS) -> list[float]:
    rng = np.random.default_rng(20260812)
    index = np.arange(count)
    trend = 400.0 + 1.5 * index
    season = 60.0 * np.sin(index * 2.0 * np.pi / 52.0)
    return list(trend + season + rng.normal(0.0, 18.0, size=count))


class TestStagesAreTimed:
    def test_a_stage_records_even_when_its_body_raises(self) -> None:
        timings = RunTimings()

        with pytest.raises(ValueError), timings.measure(Stage.FIT):
            raise ValueError("model diverged")

        assert timings.seconds_in(Stage.FIT) >= 0.0
        assert [t.stage for t in timings.stages] == [Stage.FIT]

    def test_an_overrunning_stage_is_named_even_when_the_total_fits(self) -> None:
        timings = RunTimings()
        timings.record(Stage.PARSE, STAGE_BUDGET_SECONDS[Stage.PARSE] + 1.0)

        assert timings.within_budget
        assert [t.stage for t in timings.overruns] == [Stage.PARSE]
        assert timings.as_dict()["overruns"] == ["parse"]

    def test_the_stage_budgets_leave_slack_under_the_total(self) -> None:
        assert sum(STAGE_BUDGET_SECONDS.values()) < TOTAL_BUDGET_SECONDS

    def test_every_stage_has_a_budget(self) -> None:
        assert set(STAGE_BUDGET_SECONDS) == set(Stage)

    def test_the_report_carries_the_budget_beside_the_measurement(self) -> None:
        timings = RunTimings()
        timings.record(Stage.FIT, 1.25)

        payload = timings.as_dict()
        stage = payload["stages"][0]  # type: ignore[index]

        assert stage["stage"] == "fit"
        assert stage["budget"] == STAGE_BUDGET_SECONDS[Stage.FIT]
        assert stage["over"] is False
        assert payload["budget_seconds"] == TOTAL_BUDGET_SECONDS


class TestTheCeilingIsEnforcedNotDocumented:
    def test_a_normal_file_runs_inline(self) -> None:
        decision = admission(120)

        assert decision.admission is Admission.INLINE
        assert decision.accepted

    def test_past_the_ceiling_the_run_is_queued_and_says_so(self) -> None:
        decision = admission(SERIES_CEILING + 1)

        assert decision.admission is Admission.QUEUE
        assert decision.accepted
        assert "progress" in decision.message
        assert f"{SERIES_CEILING:,}" in decision.message

    def test_past_the_hard_limit_the_run_is_refused_with_advice(self) -> None:
        decision = admission(SERIES_HARD_LIMIT + 1)

        assert decision.admission is Admission.REFUSE
        assert not decision.accepted
        assert "group by" in decision.message

    def test_the_boundary_is_the_ceiling_itself_not_one_past_it(self) -> None:
        assert admission(SERIES_CEILING).admission is Admission.INLINE
        assert admission(SERIES_HARD_LIMIT).admission is Admission.QUEUE

    def test_the_decision_carries_the_numbers_it_was_made_from(self) -> None:
        payload = admission(SERIES_CEILING + 5).as_dict()

        assert payload["ceiling"] == SERIES_CEILING
        assert payload["hard_limit"] == SERIES_HARD_LIMIT
        assert payload["series_count"] == SERIES_CEILING + 5


class TestPercentile:
    def test_nearest_rank_picks_a_value_that_was_observed(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]

        assert percentile(values, 0.95) in values
        assert percentile(values, 0.95) == 5.0
        assert percentile(values, 0.5) == 3.0

    def test_an_empty_sample_has_no_percentile(self) -> None:
        assert np.isnan(percentile([], 0.95))


class TestTheReferenceRunFitsTheBudget:
    """The assertion the SLO actually rests on.

    Marked slow because it fits real models five times. It is the only test
    here that would catch a model roster that quietly doubled the fit time.
    """

    @pytest.mark.slow
    def test_p95_of_the_reference_dataset_is_under_a_minute(self) -> None:
        periods = weeks()
        values = reference_series()

        elapsed: list[float] = []
        timings: list[RunTimings] = []
        for _ in range(REFERENCE_RUNS):
            started = time.perf_counter()
            output = run_forecast(
                ForecastInput(
                    series=SeriesInput(periods=periods, values=values),
                    frequency=WEEKLY,
                    horizon=REFERENCE_HORIZON,
                )
            )
            elapsed.append(time.perf_counter() - started)
            timings.append(output.timings)

        p95 = percentile(elapsed, 0.95)
        slowest_stage = max(
            (t for run in timings for t in run.stages),
            key=lambda t: t.seconds,
        )

        assert p95 < TOTAL_BUDGET_SECONDS, (
            f"p95 of {REFERENCE_RUNS} runs was {p95:.1f}s against a {TOTAL_BUDGET_SECONDS:.0f}s "
            f"budget; slowest stage was {slowest_stage.stage.value} at {slowest_stage.seconds:.1f}s"
        )

    @pytest.mark.slow
    def test_the_run_reports_where_its_time_went(self) -> None:
        output = run_forecast(
            ForecastInput(
                series=SeriesInput(periods=weeks(), values=reference_series()),
                frequency=WEEKLY,
                horizon=REFERENCE_HORIZON,
            )
        )

        recorded = {timing.stage for timing in output.timings.stages}

        assert {Stage.CLASSIFY, Stage.FIT, Stage.PREDICT, Stage.CALIBRATE} <= recorded
        assert output.timings.total > 0
        # And it travels with the run rather than only being logged.
        assert output.diagnostics["timings"] == output.timings.as_dict()

    @pytest.mark.slow
    def test_fitting_is_where_the_time_goes_and_it_is_inside_its_own_budget(self) -> None:
        output = run_forecast(
            ForecastInput(
                series=SeriesInput(periods=weeks(), values=reference_series()),
                frequency=WEEKLY,
                horizon=REFERENCE_HORIZON,
            )
        )

        assert output.timings.seconds_in(Stage.FIT) <= STAGE_BUDGET_SECONDS[Stage.FIT], (
            f"fitting took {output.timings.seconds_in(Stage.FIT):.1f}s against a "
            f"{STAGE_BUDGET_SECONDS[Stage.FIT]:.0f}s budget"
        )
