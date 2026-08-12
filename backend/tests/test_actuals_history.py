"""A restated actual never changes what a model was scored against.

Late invoices, processed returns and corrected counts all move a number for a
week that closed weeks ago. If the correction overwrites the old reading then
every accuracy figure computed before it moves too, quietly, and a model that
was not touched looks worse than it did yesterday.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.append_only import AppendOnlyViolation
from app.models.entities import Dataset
from app.models.enums import DatasetStatus
from app.services import actuals_service as actuals
from app.services.actuals_service import Reading, series_key

JANUARY = date(2026, 1, 5)
FEBRUARY = date(2026, 2, 2)

FIRST_READ = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
RESTATEMENT = datetime(2026, 3, 9, 9, 0, tzinfo=UTC)


async def _dataset(session: AsyncSession) -> Dataset:
    dataset = Dataset(name="actuals fixture", status=DatasetStatus.READY)
    session.add(dataset)
    await session.flush()
    return dataset


class TestARestatementIsAddedNotSubstituted:
    async def test_both_readings_survive(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)

        await actuals.record(
            session, dataset.id, [Reading("", JANUARY, 1200.0)], revised_at=FIRST_READ
        )
        await actuals.record(
            session, dataset.id, [Reading("", JANUARY, 1340.0)], revised_at=RESTATEMENT
        )
        await session.commit()

        history = await actuals.revisions(session, dataset.id, "", JANUARY)

        assert [row.value for row in history] == [1200.0, 1340.0]
        assert [row.revised_at.replace(tzinfo=UTC) for row in history] == [FIRST_READ, RESTATEMENT]

    async def test_scoring_replays_what_the_run_was_scored_against(
        self, session: AsyncSession
    ) -> None:
        dataset = await _dataset(session)
        await actuals.record(
            session, dataset.id, [Reading("", JANUARY, 1200.0)], revised_at=FIRST_READ
        )
        await actuals.record(
            session, dataset.id, [Reading("", JANUARY, 1340.0)], revised_at=RESTATEMENT
        )
        await session.commit()

        scored_then = await actuals.current(session, dataset.id, as_of=FIRST_READ)
        believed_now = await actuals.current(session, dataset.id)

        assert scored_then[("", JANUARY)] == 1200.0
        assert believed_now[("", JANUARY)] == 1340.0

    async def test_a_reading_recorded_after_the_moment_asked_about_is_invisible(
        self, session: AsyncSession
    ) -> None:
        dataset = await _dataset(session)
        await actuals.record(
            session, dataset.id, [Reading("", JANUARY, 1200.0)], revised_at=RESTATEMENT
        )
        await session.commit()

        assert await actuals.current(session, dataset.id, as_of=FIRST_READ) == {}

    async def test_a_reading_cannot_be_edited_once_written(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        await actuals.record(
            session, dataset.id, [Reading("", JANUARY, 1200.0)], revised_at=FIRST_READ
        )
        await session.commit()

        history = await actuals.revisions(session, dataset.id, "", JANUARY)
        history[0].value = 9999.0

        with pytest.raises(AppendOnlyViolation, match="actual_observations"):
            await session.flush()

    async def test_a_reading_cannot_be_deleted(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        await actuals.record(
            session, dataset.id, [Reading("", JANUARY, 1200.0)], revised_at=FIRST_READ
        )
        await session.commit()

        history = await actuals.revisions(session, dataset.id, "", JANUARY)
        await session.delete(history[0])

        with pytest.raises(AppendOnlyViolation, match="actual_observations"):
            await session.flush()


class TestReUploadingTheSameFile:
    async def test_an_unchanged_number_does_not_manufacture_a_revision(
        self, session: AsyncSession
    ) -> None:
        dataset = await _dataset(session)
        batch = [Reading("", JANUARY, 1200.0), Reading("", FEBRUARY, 900.0)]

        first = await actuals.record(session, dataset.id, batch, revised_at=FIRST_READ)
        second = await actuals.record(session, dataset.id, batch, revised_at=RESTATEMENT)
        await session.commit()

        assert first == 2
        assert second == 0
        assert len(await actuals.revisions(session, dataset.id, "", JANUARY)) == 1

    async def test_only_the_numbers_that_moved_are_written(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        await actuals.record(
            session,
            dataset.id,
            [Reading("", JANUARY, 1200.0), Reading("", FEBRUARY, 900.0)],
            revised_at=FIRST_READ,
        )

        written = await actuals.record(
            session,
            dataset.id,
            [Reading("", JANUARY, 1200.0), Reading("", FEBRUARY, 950.0)],
            revised_at=RESTATEMENT,
        )
        await session.commit()

        assert written == 1
        assert len(await actuals.revisions(session, dataset.id, "", JANUARY)) == 1
        assert len(await actuals.revisions(session, dataset.id, "", FEBRUARY)) == 2


class TestWhichPeriodsNeedRescoring:
    async def test_restatements_since_a_moment_are_listed(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        await actuals.record(
            session,
            dataset.id,
            [Reading("", JANUARY, 1200.0), Reading("", FEBRUARY, 900.0)],
            revised_at=FIRST_READ,
        )
        await actuals.record(
            session, dataset.id, [Reading("", JANUARY, 1340.0)], revised_at=RESTATEMENT
        )
        await session.commit()

        moved = await actuals.restated_since(session, dataset.id, FIRST_READ)

        assert moved == [("", JANUARY)]


class TestSeriesKeysAreStable:
    def test_the_same_grain_keys_the_same_way_whatever_order_it_was_built_in(self) -> None:
        assert series_key({"region": "North", "channel": "Retail"}) == series_key(
            {"channel": "Retail", "region": "North"}
        )

    def test_the_whole_business_total_has_an_empty_key(self) -> None:
        assert series_key(None) == ""
        assert series_key({}) == ""

    def test_different_grains_do_not_collide(self) -> None:
        assert series_key({"region": "North"}) != series_key({"region": "South"})
        assert series_key({"region": "North"}) != series_key({"channel": "North"})

    async def test_two_series_in_one_dataset_are_kept_apart(self, session: AsyncSession) -> None:
        dataset = await _dataset(session)
        north = series_key({"region": "North"})
        south = series_key({"region": "South"})

        await actuals.record(
            session,
            dataset.id,
            [Reading(north, JANUARY, 700.0), Reading(south, JANUARY, 500.0)],
            revised_at=FIRST_READ,
        )
        await session.commit()

        in_force = await actuals.current(session, dataset.id)

        assert in_force[(north, JANUARY)] == 700.0
        assert in_force[(south, JANUARY)] == 500.0
