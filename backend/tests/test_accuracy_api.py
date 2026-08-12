from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Dataset,
    ForecastPoint,
    ForecastRun,
    ForecastSeries,
    ModelCandidate,
)
from app.models.enums import (
    DatasetStatus,
    ForecastFrequency,
    ModelKind,
    PointKind,
    RunStatus,
    SeriesStatus,
)
from app.services import accuracy_service


async def _run(session: AsyncSession, *, scored: bool = True) -> ForecastRun:
    dataset = Dataset(name="accuracy fixture", status=DatasetStatus.READY)
    session.add(dataset)
    await session.flush()

    run = ForecastRun(
        dataset_id=dataset.id,
        name="accuracy run",
        time_column="week",
        target_column="units",
        frequency=ForecastFrequency.WEEKLY,
        horizon=4,
        confidence_level=0.8,
        status=RunStatus.COMPLETED,
        selected_model=ModelKind.HOLT_WINTERS,
        options={"backtest_scheme": "rolling"},
        scored_at=datetime(2026, 3, 1, tzinfo=UTC) if scored else None,
    )
    session.add(run)
    await session.flush()

    start = date(2026, 1, 5)
    for step in range(4):
        session.add(
            ForecastPoint(
                run_id=run.id,
                period=start + timedelta(weeks=step),
                kind=PointKind.FORECAST,
                forecast=100.0 + 10.0 * step,
                actual=100.0,
                lower_bound=80.0,
                upper_bound=130.0,
            )
        )

    session.add_all(
        [
            ModelCandidate(
                run_id=run.id,
                model=ModelKind.HOLT_WINTERS,
                rank=1,
                selected=True,
                wmape=12.0,
                folds=6,
            ),
            ModelCandidate(
                run_id=run.id, model=ModelKind.SEASONAL_NAIVE, rank=2, wmape=20.0, folds=6
            ),
            ModelCandidate(run_id=run.id, model=ModelKind.NAIVE, rank=3, wmape=24.0, folds=6),
        ]
    )
    session.add_all(
        [
            ForecastSeries(
                run_id=run.id,
                label="Chilled",
                key={"demand_class": "smooth"},
                status=SeriesStatus.FORECAST,
                realized_wmape=11.0,
            ),
            ForecastSeries(
                run_id=run.id,
                label="Spares",
                key={"demand_class": "lumpy"},
                status=SeriesStatus.FORECAST,
                realized_wmape=48.0,
            ),
        ]
    )
    await session.commit()
    return run


async def _grouped_run(
    session: AsyncSession,
    *,
    combinations: int = 10,
    band: tuple[float, float] = (80.0, 130.0),
    outside: int = 0,
) -> ForecastRun:
    run = await _run(session)
    lower, upper = band

    start = date(2026, 1, 5)
    for index in range(combinations):
        series = ForecastSeries(
            run_id=run.id,
            label=f"Line {index}",
            key={"demand_class": "smooth", "line": str(index)},
            status=SeriesStatus.FORECAST,
        )
        session.add(series)
        await session.flush()

        for step in range(4):
            session.add(
                ForecastPoint(
                    run_id=run.id,
                    series_id=series.id,
                    period=start + timedelta(weeks=step),
                    kind=PointKind.FORECAST,
                    forecast=100.0,
                    actual=upper + 50.0 if index < outside else 100.0,
                    lower_bound=lower,
                    upper_bound=upper,
                )
            )
    await session.commit()
    return run


class TestTheRangeIsHeldToItsPromise:
    async def test_too_few_finished_periods_says_so_instead_of_claiming_perfect(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)

        report = await accuracy_service.build(session, run.id)

        assert report is not None
        assert [row["horizon"] for row in report.coverage] == [1, 2, 3, 4]
        assert all(row["observed"] == 1.0 for row in report.coverage)
        assert all(row["measurable"] is False for row in report.coverage)
        assert any("Too few finished periods" in caveat for caveat in report.caveats)

    async def test_a_range_that_keeps_its_promise_draws_no_caveat(
        self, session: AsyncSession
    ) -> None:
        run = await _grouped_run(session, combinations=10, outside=2)

        report = await accuracy_service.build(session, run.id)

        assert report is not None
        measured = [row for row in report.coverage if row["measurable"]]
        assert measured, "eleven observations a horizon is enough to judge"
        assert all(row["observed"] == pytest.approx(9 / 11, abs=1e-4) for row in measured)
        assert not any("range" in caveat for caveat in report.caveats)

    async def test_a_range_narrower_than_it_claims_is_called_out(
        self, session: AsyncSession
    ) -> None:
        run = await _grouped_run(session, combinations=10, outside=6)

        report = await accuracy_service.build(session, run.id)

        assert report is not None
        assert all(row["holds"] is False for row in report.coverage if row["measurable"])
        assert any("narrower than it claims" in caveat for caveat in report.caveats)

    async def test_the_share_is_measured_against_the_level_the_run_published(
        self, session: AsyncSession
    ) -> None:
        run = await _grouped_run(session)

        report = await accuracy_service.build(session, run.id)

        assert report is not None
        assert {row["nominal"] for row in report.coverage} == {run.confidence_level}


class TestAccuracyByHorizon:
    async def test_a_horizon_pools_every_series_that_shares_the_period(
        self, session: AsyncSession
    ) -> None:
        run = await _grouped_run(session, combinations=10)

        report = await accuracy_service.build(session, run.id)

        assert report is not None
        assert [row.horizon for row in report.by_horizon] == [1, 2, 3, 4]
        assert [row.observations for row in report.by_horizon] == [11, 11, 11, 11]


    async def test_error_is_reported_per_horizon_not_only_in_aggregate(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)

        report = await accuracy_service.build(session, run.id)

        assert report is not None
        assert [row.horizon for row in report.by_horizon] == [1, 2, 3, 4]

    async def test_a_forecast_that_drifts_high_shows_it_growing_with_the_horizon(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)

        report = await accuracy_service.build(session, run.id)
        assert report is not None
        errors = [row.wape for row in report.by_horizon]

        assert errors[0] == 0.0
        assert errors == sorted(errors), f"error did not grow with horizon: {errors}"

    async def test_bias_is_signed_and_separate_from_error(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)

        report = await accuracy_service.build(session, run.id)
        assert report is not None
        later = report.by_horizon[-1]

        assert later.bias_pct is not None
        assert later.bias_pct > 0, "a forecast running high must show positive bias"
        assert later.wape is not None and later.wape > 0


class TestAccuracyBySeriesClass:
    async def test_each_demand_class_is_reported_separately(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)

        report = await accuracy_service.build(session, run.id)
        assert report is not None
        classes = {row.demand_class: row for row in report.by_class}

        assert set(classes) == {"smooth", "lumpy"}
        assert classes["smooth"].wape == 11.0
        assert classes["lumpy"].wape == 48.0

    async def test_a_lumpy_class_does_not_claim_a_point_forecast(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)

        report = await accuracy_service.build(session, run.id)
        assert report is not None
        classes = {row.demand_class: row for row in report.by_class}

        assert classes["lumpy"].point_forecast_claimed is False
        assert classes["smooth"].point_forecast_claimed is True


class TestValueOverBaseline:
    async def test_the_model_is_compared_against_the_best_baseline_that_ran(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)

        report = await accuracy_service.build(session, run.id)
        assert report is not None
        value = report.value_add

        assert value is not None
        assert value.model == ModelKind.HOLT_WINTERS.value
        assert value.baseline == ModelKind.SEASONAL_NAIVE.value
        assert value.improvement_pct == 40.0
        assert value.beats_baseline

    async def test_a_model_that_loses_to_the_baseline_says_so(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)
        candidates = (await accuracy_service.build(session, run.id)) is not None
        assert candidates

        from sqlalchemy import select

        rows = (
            await session.execute(select(ModelCandidate).where(ModelCandidate.run_id == run.id))
        ).scalars().all()
        winner = next(c for c in rows if c.selected)
        baseline = next(c for c in rows if c.model is ModelKind.SEASONAL_NAIVE)

        value = accuracy_service.value_add([winner, baseline])
        worse = accuracy_service.value_add(
            [
                ModelCandidate(run_id=run.id, model=ModelKind.HOLT_WINTERS, selected=True, wmape=30.0),
                ModelCandidate(run_id=run.id, model=ModelKind.SEASONAL_NAIVE, wmape=20.0),
            ]
        )

        assert value is not None and value.beats_baseline
        assert worse is not None and not worse.beats_baseline
        assert worse.improvement_pct is not None and worse.improvement_pct < 0


class TestEveryFigureIsTraceable:
    async def test_the_report_names_the_run_and_the_backtest_behind_it(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)

        report = await accuracy_service.build(session, run.id)
        assert report is not None
        payload = report.as_dict()

        assert payload["run_id"] == str(run.id)
        assert payload["backtest"]["scheme"] == "rolling"
        assert payload["backtest"]["origins"] == 6
        assert payload["backtest"]["horizon"] == 4

    async def test_the_report_names_the_code_and_settings_behind_it(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)

        payload = (await accuracy_service.build(session, run.id)).as_dict()  # type: ignore[union-attr]

        provenance = payload["provenance"]
        assert set(provenance) == {
            "code_version",
            "model_version",
            "feature_version",
            "config_hash",
        }
        assert all(provenance.values())

    async def test_a_backtest_only_run_does_not_present_itself_as_realised(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session, scored=False)

        report = await accuracy_service.build(session, run.id)

        assert report is not None
        assert report.measured_against_outcomes is False
        assert any("held-out" in caveat for caveat in report.caveats)

    async def test_a_scored_run_says_it_was_scored(self, session: AsyncSession) -> None:
        run = await _run(session, scored=True)

        report = await accuracy_service.build(session, run.id)

        assert report is not None
        assert report.measured_against_outcomes is True
        assert report.as_dict()["scored_at"] is not None

    async def test_an_unknown_run_has_no_report_rather_than_an_empty_one(
        self, session: AsyncSession
    ) -> None:
        import uuid

        assert await accuracy_service.build(session, uuid.uuid4()) is None

    async def test_the_whole_report_serialises(self, session: AsyncSession) -> None:
        import json

        run = await _run(session)

        payload = json.loads(
            json.dumps((await accuracy_service.build(session, run.id)).as_dict())  # type: ignore[union-attr]
        )

        assert payload["run_id"] == str(run.id)
        assert isinstance(payload["by_horizon"], list)
        assert isinstance(payload["by_class"], list)
        assert payload["coverage_tolerance_pp"] == 5.0


class TestTheHeadlineFigure:
    async def test_with_nothing_scored_there_is_no_number_to_publish(
        self, session: AsyncSession
    ) -> None:
        headline = await accuracy_service.headline(session)

        assert headline.accuracy_pct is None
        assert headline.publishable is False

    async def test_one_run_is_not_enough_evidence_for_a_homepage_claim(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)
        run.realized_wmape = 6.0
        run.scored_periods = 52
        await session.commit()

        headline = await accuracy_service.headline(session)

        assert headline.accuracy_pct == 94.0
        assert headline.runs_scored == 1
        assert headline.publishable is False, "a single run must not become the headline"

    async def test_enough_runs_over_enough_periods_becomes_publishable(
        self, session: AsyncSession
    ) -> None:
        for _ in range(3):
            run = await _run(session)
            run.realized_wmape = 6.0
            run.scored_periods = 20
            await session.commit()

        headline = await accuracy_service.headline(session)

        assert headline.runs_scored == 3
        assert headline.periods_scored == 60
        assert headline.publishable is True
        assert headline.accuracy_pct == 94.0

    async def test_a_run_that_scored_more_periods_carries_more_weight(
        self, session: AsyncSession
    ) -> None:
        big = await _run(session)
        big.realized_wmape = 4.0
        big.scored_periods = 90
        small = await _run(session)
        small.realized_wmape = 40.0
        small.scored_periods = 10
        await session.commit()

        headline = await accuracy_service.headline(session)

        assert headline.accuracy_pct == 92.4

    async def test_the_figure_carries_what_stands_behind_it(
        self, session: AsyncSession
    ) -> None:
        run = await _run(session)
        run.realized_wmape = 6.0
        run.scored_periods = 30
        await session.commit()

        payload = (await accuracy_service.headline(session)).as_dict()

        assert payload["runs_scored"] == 1
        assert payload["periods_scored"] == 30
        assert payload["minimum_runs"] == accuracy_service.MIN_RUNS_FOR_HEADLINE
        assert payload["minimum_periods"] == accuracy_service.MIN_PERIODS_FOR_HEADLINE


class TestOverHttp:
    async def test_the_endpoint_serves_the_report_for_a_real_run(
        self, session: AsyncSession, client
    ) -> None:
        run = await _run(session)

        response = await client.get(f"/api/forecasts/{run.id}/accuracy")

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == str(run.id)
        assert payload["forecast_value_add"]["beats_baseline"] is True
        assert [row["horizon"] for row in payload["by_horizon"]] == [1, 2, 3, 4]

    async def test_an_unknown_run_is_a_404_not_an_empty_report(self, client) -> None:
        import uuid

        response = await client.get(f"/api/forecasts/{uuid.uuid4()}/accuracy")

        assert response.status_code == 404

    async def test_the_headline_route_is_not_shadowed_by_the_run_route(self, client) -> None:
        response = await client.get("/api/forecasts/accuracy/headline")

        assert response.status_code == 200
        assert "publishable" in response.json()
