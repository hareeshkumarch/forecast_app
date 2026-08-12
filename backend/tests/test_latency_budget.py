from __future__ import annotations

import csv
import io
import time
import uuid
from datetime import date, timedelta

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.core.errors import ValidationError
from app.forecasting.engine import ForecastInput, SeriesInput, run_forecast
from app.models.enums import ForecastFrequency
from app.services import dataset_service, forecast_service

WEEKLY = ForecastFrequency.WEEKLY

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


def grained_csv(combinations: int, periods: int = 14) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["week", "sku", "units"])
    days = weeks(periods)
    for index in range(combinations):
        writer.writerow([days[index % periods].isoformat(), f"sku-{index}", 100.0 + index % 40])
    return buffer.getvalue().encode("utf-8")


async def dataset_with(session: AsyncSession, combinations: int) -> uuid.UUID:
    dataset, _profile = await dataset_service.create_from_upload(
        session, grained_csv(combinations), "grain.csv", name=f"{combinations} combinations"
    )
    await session.commit()
    return dataset.id


class TestTheCeilingIsEnforcedOnRunsNotJustDescribed:
    async def test_a_grain_past_the_hard_limit_is_refused_before_a_run_exists(
        self, session: AsyncSession
    ) -> None:
        dataset_id = await dataset_with(session, SERIES_HARD_LIMIT + 1)

        with pytest.raises(ValidationError) as raised:
            await forecast_service.create_run(
                session, dataset_id=dataset_id, group_by=["sku"], horizon=3
            )

        assert raised.value.detail["admission"] == "refuse"
        assert raised.value.detail["series_count"] == SERIES_HARD_LIMIT + 1
        assert "group by product, region or channel" in raised.value.message

        runs = await forecast_service.list_runs(session)
        assert runs.total == 0, "a refused grain leaves nothing behind"

    async def test_a_grain_past_the_ceiling_is_admitted_and_says_it_is_queued(
        self, session: AsyncSession
    ) -> None:
        dataset_id = await dataset_with(session, SERIES_CEILING + 1)

        run = await forecast_service.create_run(
            session, dataset_id=dataset_id, group_by=["sku"], horizon=3
        )

        assert run.options["admission"]["admission"] == "queue"
        assert run.options["admission"]["series_count"] == SERIES_CEILING + 1

    async def test_an_ordinary_grain_runs_inline(self, session: AsyncSession) -> None:
        dataset_id = await dataset_with(session, 20)

        run = await forecast_service.create_run(
            session, dataset_id=dataset_id, group_by=["sku"], horizon=3
        )

        assert run.options["admission"]["admission"] == "inline"
        assert run.options["admission"]["series_count"] == 20

    async def test_an_ungrouped_run_is_one_series(self, session: AsyncSession) -> None:
        dataset_id = await dataset_with(session, 20)

        run = await forecast_service.create_run(session, dataset_id=dataset_id, horizon=3)

        assert run.options["admission"]["series_count"] == 1
        assert run.options["admission"]["admission"] == "inline"


class TestPercentile:
    def test_nearest_rank_picks_a_value_that_was_observed(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]

        assert percentile(values, 0.95) in values
        assert percentile(values, 0.95) == 5.0
        assert percentile(values, 0.5) == 3.0

    def test_an_empty_sample_has_no_percentile(self) -> None:
        assert np.isnan(percentile([], 0.95))


class TestTheReferenceRunFitsTheBudget:

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
