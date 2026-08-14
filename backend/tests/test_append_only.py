from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.append_only import AppendOnlyViolation
from app.models.entities import Dataset, ForecastPoint, ForecastRun
from app.models.enums import DatasetStatus, ForecastFrequency, PointKind, RunStatus


async def _dataset(session: AsyncSession) -> Dataset:
    dataset = Dataset(name="append-only fixture", status=DatasetStatus.READY)
    session.add(dataset)
    await session.flush()
    return dataset


async def _run(session: AsyncSession, dataset: Dataset) -> ForecastRun:
    run = ForecastRun(
        dataset_id=dataset.id,
        name="append-only run",
        time_column="week",
        target_column="units",
        frequency=ForecastFrequency.WEEKLY,
        horizon=4,
        status=RunStatus.COMPLETED,
    )
    session.add(run)
    await session.flush()
    return run


async def _point(session: AsyncSession, run: ForecastRun, value: float) -> ForecastPoint:
    point = ForecastPoint(
        run_id=run.id,
        period=date(2026, 1, 5),
        kind=PointKind.FORECAST,
        forecast=value,
        lower_bound=value - 10.0,
        upper_bound=value + 10.0,
    )
    session.add(point)
    await session.flush()
    return point


class TestIssuedForecastsAreImmutable:
    async def test_updating_a_forecast_point_is_refused(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        run = await _run(session, dataset)
        point = await _point(session, run, 120.0)
        await session.commit()

        point.forecast = 999.0

        with pytest.raises(AppendOnlyViolation, match="append-only"):
            await session.flush()

    async def test_deleting_a_forecast_point_is_refused(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        run = await _run(session, dataset)
        point = await _point(session, run, 120.0)
        await session.commit()

        await session.delete(point)

        with pytest.raises(AppendOnlyViolation, match="append-only"):
            await session.flush()

    async def test_the_refusal_names_what_it_refused(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        run = await _run(session, dataset)
        point = await _point(session, run, 50.0)
        await session.commit()

        point.upper_bound = 5000.0

        with pytest.raises(AppendOnlyViolation) as caught:
            await session.flush()

        message = str(caught.value)
        assert "forecast_points" in message
        assert "new run_id" in message


class TestRerunningProducesASecondRun:
    async def test_two_runs_over_one_dataset_both_persist_and_are_retrievable(
        self, session: AsyncSession
    ) -> None:
        dataset = await _dataset(session)

        first = await _run(session, dataset)
        await _point(session, first, 100.0)
        second = await _run(session, dataset)
        await _point(session, second, 140.0)
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(ForecastPoint).where(ForecastPoint.run_id.in_([first.id, second.id]))
                )
            )
            .scalars()
            .all()
        )

        assert first.id != second.id
        assert {row.run_id for row in rows} == {first.id, second.id}
        assert sorted(row.forecast for row in rows if row.forecast is not None) == [100.0, 140.0]

    async def test_the_earlier_run_is_untouched_by_the_later_one(
        self, session: AsyncSession
    ) -> None:
        dataset = await _dataset(session)
        first = await _run(session, dataset)
        original = await _point(session, first, 100.0)
        await session.commit()
        before = (original.forecast, original.lower_bound, original.upper_bound)

        second = await _run(session, dataset)
        await _point(session, second, 140.0)
        await session.commit()

        refetched = (
            await session.execute(select(ForecastPoint).where(ForecastPoint.run_id == first.id))
        ).scalar_one()

        assert (refetched.forecast, refetched.lower_bound, refetched.upper_bound) == before


class TestLaterFactsAreNotRewrites:
    async def test_an_actual_can_be_recorded_after_the_period_finishes(
        self, session: AsyncSession
    ) -> None:
        dataset = await _dataset(session)
        run = await _run(session, dataset)
        point = await _point(session, run, 120.0)
        await session.commit()

        point.actual = 131.0
        await session.flush()

        assert point.actual == 131.0
        assert point.forecast == 120.0

    async def test_recording_the_actual_cannot_smuggle_in_a_new_forecast(
        self, session: AsyncSession
    ) -> None:
        dataset = await _dataset(session)
        run = await _run(session, dataset)
        point = await _point(session, run, 120.0)
        await session.commit()

        point.actual = 131.0
        point.forecast = 130.0

        with pytest.raises(AppendOnlyViolation, match="forecast_points.forecast"):
            await session.flush()

    async def test_writing_a_column_its_own_value_is_not_a_rewrite(
        self, session: AsyncSession
    ) -> None:
        dataset = await _dataset(session)
        run = await _run(session, dataset)
        point = await _point(session, run, 120.0)
        await session.commit()

        point.forecast = 120.0
        await session.flush()

        assert point.forecast == 120.0


class TestOrdinaryTablesStillMutate:
    async def test_a_dataset_can_still_be_renamed(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        await session.commit()

        dataset.name = "renamed"
        await session.flush()

        assert dataset.name == "renamed"

    async def test_a_run_can_still_change_status(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        run = await _run(session, dataset)
        await session.commit()

        run.status = RunStatus.FAILED
        await session.flush()

        assert run.status == RunStatus.FAILED

    async def test_an_unrelated_id_is_not_caught_by_the_guard(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        await session.commit()
        assert isinstance(dataset.id, uuid.UUID)
