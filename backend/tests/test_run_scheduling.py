from __future__ import annotations

import asyncio
import uuid

import pytest

from app.services.job_runner import MODEL_SEARCH, SERIES_CHUNK, Scheduler


@pytest.fixture
def two_slots():
    scheduler = Scheduler()
    scheduler._slots = 2
    return scheduler


async def _hold(scheduler: Scheduler, run_id: uuid.UUID, kind: str = MODEL_SEARCH):
    await scheduler.acquire(run_id, kind)
    return run_id


async def test_up_to_the_worker_count_starts_at_once(two_slots) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()

    await two_slots.acquire(first, MODEL_SEARCH)
    await two_slots.acquire(second, MODEL_SEARCH)

    assert two_slots.running == 2
    assert two_slots.queued == 0


async def test_the_third_waits_and_knows_where_it_is(two_slots) -> None:
    held = [uuid.uuid4(), uuid.uuid4()]
    for run_id in held:
        await two_slots.acquire(run_id, MODEL_SEARCH)

    third, fourth = uuid.uuid4(), uuid.uuid4()
    waiting = [
        asyncio.create_task(_hold(two_slots, third)),
        asyncio.create_task(_hold(two_slots, fourth)),
    ]
    await asyncio.sleep(0)

    assert two_slots.queued == 2
    assert two_slots.position_of(third) == 0
    assert two_slots.position_of(fourth) == 1

    for run_id in held:
        two_slots.release(run_id)
    await asyncio.gather(*waiting)

    assert two_slots.position_of(third) is None
    assert two_slots.running == 2


async def test_a_run_that_is_running_is_not_reported_as_waiting(two_slots) -> None:
    run_id = uuid.uuid4()
    await two_slots.acquire(run_id, MODEL_SEARCH)

    assert two_slots.position_of(run_id) is None


async def test_a_free_slot_is_not_taken_over_the_head_of_a_queue(two_slots) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    await two_slots.acquire(first, MODEL_SEARCH)
    await two_slots.acquire(second, MODEL_SEARCH)

    early = uuid.uuid4()
    queued = asyncio.create_task(_hold(two_slots, early))
    await asyncio.sleep(0)

    latecomer = uuid.uuid4()
    jumper = asyncio.create_task(_hold(two_slots, latecomer))
    await asyncio.sleep(0)

    two_slots.release(first)
    await asyncio.sleep(0)

    assert queued.done()
    assert not jumper.done()

    two_slots.release(second)
    await jumper


async def test_one_run_on_its_own_still_gets_the_whole_pool(two_slots) -> None:
    grouped = uuid.uuid4()

    await two_slots.acquire(grouped, SERIES_CHUNK)
    await two_slots.acquire(grouped, SERIES_CHUNK)

    assert two_slots.running == 2


async def test_a_grouped_run_cannot_hold_every_worker_against_another_run(two_slots) -> None:
    grouped, other = uuid.uuid4(), uuid.uuid4()

    await two_slots.acquire(grouped, SERIES_CHUNK)
    await two_slots.acquire(grouped, SERIES_CHUNK)

    chunks = [asyncio.create_task(_hold(two_slots, grouped, SERIES_CHUNK)) for _ in range(6)]
    await asyncio.sleep(0)
    newcomer = asyncio.create_task(_hold(two_slots, other))
    await asyncio.sleep(0)

    two_slots.release(grouped)
    await asyncio.sleep(0)

    assert newcomer.done()

    two_slots.release(grouped)
    for _ in range(8):
        await asyncio.sleep(0)
        for task in chunks:
            if task.done():
                two_slots.release(grouped)
    two_slots.forget_all()
    for task in [*chunks, newcomer]:
        task.cancel()
    await asyncio.gather(*chunks, newcomer, return_exceptions=True)


async def test_a_cancelled_run_does_not_leave_a_slot_behind(two_slots) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    await two_slots.acquire(first, MODEL_SEARCH)
    await two_slots.acquire(second, MODEL_SEARCH)

    abandoned = asyncio.create_task(_hold(two_slots, uuid.uuid4()))
    await asyncio.sleep(0)
    abandoned.cancel()
    await asyncio.gather(abandoned, return_exceptions=True)

    assert two_slots.queued == 0

    two_slots.release(first)
    two_slots.release(second)
    assert two_slots.running == 0


async def test_the_queue_is_reportable(two_slots) -> None:
    running, waiting = uuid.uuid4(), uuid.uuid4()
    await two_slots.acquire(running, MODEL_SEARCH)
    await two_slots.acquire(running, MODEL_SEARCH)
    queued = asyncio.create_task(_hold(two_slots, waiting))
    await asyncio.sleep(0)

    rows = {row.run_id: row for row in two_slots.snapshot()}

    assert rows[running].running == 2
    assert rows[waiting].running == 0
    assert rows[waiting].waiting == 1
    assert rows[waiting].ahead == 0
    assert rows[waiting].waiting_since is not None

    two_slots.release(running)
    await queued


async def test_positions_are_announced_as_the_queue_moves(monkeypatch, two_slots) -> None:
    from app.services import job_runner

    said: list[tuple[uuid.UUID, int]] = []
    monkeypatch.setattr(
        job_runner, "announce_wait", lambda run_id, ahead, workers: said.append((run_id, ahead))
    )

    first, second = uuid.uuid4(), uuid.uuid4()
    await two_slots.acquire(first, MODEL_SEARCH)
    await two_slots.acquire(second, MODEL_SEARCH)

    third, fourth = uuid.uuid4(), uuid.uuid4()
    tasks = [
        asyncio.create_task(_hold(two_slots, third)),
        asyncio.create_task(_hold(two_slots, fourth)),
    ]
    await asyncio.sleep(0)

    assert (third, 0) in said
    assert (fourth, 1) in said

    said.clear()
    two_slots.release(first)
    await asyncio.sleep(0)

    assert (fourth, 0) in said

    two_slots.release(second)
    await asyncio.gather(*tasks)


async def test_a_series_chunk_does_not_announce_a_queue_position(monkeypatch, two_slots) -> None:
    from app.services import job_runner

    said: list[uuid.UUID] = []
    monkeypatch.setattr(
        job_runner, "announce_wait", lambda run_id, ahead, workers: said.append(run_id)
    )

    busy = uuid.uuid4()
    await two_slots.acquire(busy, MODEL_SEARCH)
    await two_slots.acquire(busy, MODEL_SEARCH)

    chunk = asyncio.create_task(_hold(two_slots, uuid.uuid4(), SERIES_CHUNK))
    await asyncio.sleep(0)

    assert said == []

    two_slots.release(busy)
    await chunk
    two_slots.forget_all()


def test_the_message_a_waiting_run_shows_names_the_reason() -> None:
    from app.services.forecast_service import _waiting_message

    assert "next in line" in _waiting_message(0)
    assert "1 run ahead" in _waiting_message(1)
    assert "3 pieces of work ahead" in _waiting_message(3)


class TestInsideOneRun:
    def test_the_opening_line_says_how_many_are_waiting_their_turn(self) -> None:
        from app.forecasting.engine import _InFlight

        assert "4 waiting their turn" in _InFlight(6, 2).opening()

    def test_a_search_with_a_lane_each_does_not_claim_a_queue(self) -> None:
        from app.forecasting.engine import _InFlight

        assert "all at once" in _InFlight(2, 4).opening()

    def test_what_is_fitting_is_named_alongside_what_is_finished(self) -> None:
        from app.forecasting.engine import _InFlight
        from app.models.enums import ModelKind

        watch = _InFlight(4, 2)
        watch.started(ModelKind.THETA)
        watch.started(ModelKind.SEASONAL_NAIVE)
        watch.finished(ModelKind.THETA)
        watch.started(ModelKind.ETS)

        line = watch.line(ModelKind.THETA)
        assert "Backtested theta (1 of 4)" in line
        assert "seasonal naive" in line
        assert "ets" in line
        assert "1 still to start" in line

    def test_the_last_completion_does_not_claim_anything_is_still_fitting(self) -> None:
        from app.forecasting.engine import _InFlight
        from app.models.enums import ModelKind

        watch = _InFlight(1, 2)
        watch.started(ModelKind.THETA)
        watch.finished(ModelKind.THETA)

        assert watch.line(ModelKind.THETA) == "Backtested theta (1 of 1)."


class TestWorkerThreads:
    def test_a_worker_pins_its_linear_algebra_to_one_thread(self, monkeypatch) -> None:
        from app.services import job_runner

        for name in job_runner._BLAS_THREAD_VARS:
            monkeypatch.delenv(name, raising=False)

        job_runner._pin_blas_threads()

        import os

        assert os.environ["OMP_NUM_THREADS"] == "1"
        assert os.environ["OPENBLAS_NUM_THREADS"] == "1"

    def test_an_operator_who_set_one_keeps_their_value(self, monkeypatch) -> None:
        from app.services import job_runner

        monkeypatch.setenv("OMP_NUM_THREADS", "4")
        job_runner._pin_blas_threads()

        import os

        assert os.environ["OMP_NUM_THREADS"] == "4"


class TestWhatAWaitingRunIsTold:
    @pytest.fixture(autouse=True)
    def _recorded(self, monkeypatch):
        from app.services import forecast_service, job_runner

        said: list[tuple[str, int | None]] = []

        async def record(run_id, progress, stage, message, queue_ahead=None):
            del run_id, progress, message
            said.append((stage, queue_ahead))
            return True

        async def straight(_self, func, *args):
            return func(*args)

        monkeypatch.setattr(forecast_service, "checkpoint_progress", record)
        monkeypatch.setattr(type(job_runner.executors), "run", straight)
        self.said = said

    @staticmethod
    async def _search(run_id: uuid.UUID, work=lambda: "output"):
        from app.services import forecast_service, job_runner

        return await job_runner.executors.run_for(
            run_id,
            MODEL_SEARCH,
            work,
            on_wait=forecast_service._queued(run_id),
            on_start=forecast_service._started(run_id),
        )

    async def test_a_run_that_gets_a_worker_is_never_told_it_is_waiting(
        self, monkeypatch, two_slots
    ) -> None:
        from app.services import job_runner

        monkeypatch.setattr(job_runner, "scheduler", two_slots)

        assert await self._search(uuid.uuid4()) == "output"
        assert [stage for stage, _ in self.said] == ["backtesting"]

    async def test_a_queued_run_is_told_where_it_is_and_then_that_it_started(
        self, monkeypatch, two_slots
    ) -> None:
        from app.services import job_runner

        monkeypatch.setattr(job_runner, "scheduler", two_slots)
        holders = [uuid.uuid4(), uuid.uuid4()]
        for run_id in holders:
            await two_slots.acquire(run_id, MODEL_SEARCH)

        search = asyncio.create_task(self._search(uuid.uuid4()))
        await asyncio.sleep(0)

        assert self.said == [("waiting", 0)]

        two_slots.release(holders[0])
        assert await search == "output"
        assert [stage for stage, _ in self.said] == ["waiting", "backtesting"]

    async def test_the_position_it_is_told_is_the_one_it_is_in(
        self, monkeypatch, two_slots
    ) -> None:
        from app.services import job_runner

        monkeypatch.setattr(job_runner, "scheduler", two_slots)
        holders = [uuid.uuid4(), uuid.uuid4()]
        for run_id in holders:
            await two_slots.acquire(run_id, MODEL_SEARCH)

        first = asyncio.create_task(self._search(uuid.uuid4()))
        await asyncio.sleep(0)
        second = asyncio.create_task(self._search(uuid.uuid4()))
        await asyncio.sleep(0)

        assert self.said == [("waiting", 0), ("waiting", 1)]

        for run_id in holders:
            two_slots.release(run_id)
        await asyncio.gather(first, second)

    async def test_the_wait_is_written_once_however_long_it_lasts(
        self, monkeypatch, two_slots
    ) -> None:
        from app.services import job_runner

        monkeypatch.setattr(job_runner, "scheduler", two_slots)
        holders = [uuid.uuid4(), uuid.uuid4()]
        for run_id in holders:
            await two_slots.acquire(run_id, MODEL_SEARCH)

        search = asyncio.create_task(self._search(uuid.uuid4()))
        await asyncio.sleep(0)
        for _ in range(3):
            two_slots._promote()

        assert self.said.count(("waiting", 0)) == 1

        two_slots.release(holders[0])
        await search
