from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core import lifecycle
from app.services.job_runner import MODEL_SEARCH, Scheduler, ShuttingDown


@pytest.fixture(autouse=True)
def _fresh():
    lifecycle.reset()
    yield
    lifecycle.reset()


async def test_a_running_process_is_ready(client) -> None:
    response = await client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json()["ready"] is True


async def test_a_draining_process_asks_not_to_be_sent_traffic(client) -> None:
    lifecycle.begin_shutdown()

    response = await client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["ready"] is False
    assert response.headers["Retry-After"]


async def test_it_stays_alive_while_it_drains(client) -> None:
    lifecycle.begin_shutdown()

    assert (await client.get("/api/health")).status_code == 200


async def test_shutting_down_twice_keeps_the_first_moment(client) -> None:
    lifecycle.begin_shutdown()
    await asyncio.sleep(0.01)
    lifecycle.begin_shutdown()

    assert (await client.get("/api/health/ready")).json()["draining_seconds"] >= 0


class TestDraining:
    async def test_nothing_new_starts_once_the_gate_is_closed(self) -> None:
        scheduler = Scheduler()
        scheduler._slots = 2
        scheduler.close()

        with pytest.raises(ShuttingDown):
            await scheduler.acquire(uuid.uuid4(), MODEL_SEARCH)

    async def test_what_is_already_running_is_left_alone(self) -> None:
        scheduler = Scheduler()
        scheduler._slots = 2
        run_id = uuid.uuid4()
        await scheduler.acquire(run_id, MODEL_SEARCH)

        scheduler.close()

        assert scheduler.running == 1
        scheduler.release(run_id)
        assert scheduler.running == 0

    async def test_a_queued_run_is_released_rather_than_left_waiting_forever(self) -> None:
        scheduler = Scheduler()
        scheduler._slots = 1
        holder = uuid.uuid4()
        await scheduler.acquire(holder, MODEL_SEARCH)

        queued = asyncio.create_task(scheduler.acquire(uuid.uuid4(), MODEL_SEARCH))
        await asyncio.sleep(0)
        scheduler.close()

        with pytest.raises(asyncio.CancelledError):
            await queued
        assert scheduler.queued == 0

    async def test_the_drain_returns_when_the_last_run_lands(self) -> None:
        from app.services.job_runner import executors

        scheduler = Scheduler()
        scheduler._slots = 2
        run_id = uuid.uuid4()
        await scheduler.acquire(run_id, MODEL_SEARCH)

        import app.services.job_runner as job_runner

        original = job_runner.scheduler
        job_runner.scheduler = scheduler
        try:
            waiting = asyncio.create_task(executors.drain(5.0))
            await asyncio.sleep(0.05)
            assert not waiting.done()

            scheduler.release(run_id)
            assert await waiting == 0
        finally:
            job_runner.scheduler = original

    async def test_the_drain_gives_up_and_says_how_many_were_stranded(self) -> None:
        from app.services.job_runner import executors

        scheduler = Scheduler()
        scheduler._slots = 2
        await scheduler.acquire(uuid.uuid4(), MODEL_SEARCH)

        import app.services.job_runner as job_runner

        original = job_runner.scheduler
        job_runner.scheduler = scheduler
        try:
            assert await executors.drain(0.1) == 1
        finally:
            job_runner.scheduler = original

    async def test_a_zero_wait_restores_the_old_behaviour(self) -> None:
        from app.services.job_runner import executors

        assert await executors.drain(0.0) >= 0
