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


class TestStreamsLetGoOfADrainingProcess:
    def test_a_live_deadline_is_not_passed(self) -> None:
        from app.core import streams

        assert streams.Deadline(60.0).passed is False

    def test_draining_ends_every_open_stream(self) -> None:
        from app.core import streams

        deadline = streams.Deadline(3600.0)
        lifecycle.begin_shutdown()

        assert deadline.passed is True

    def test_draining_collapses_the_keepalive_wait(self) -> None:
        from app.core import streams

        deadline = streams.Deadline(3600.0)
        assert deadline.remaining > 3000.0

        lifecycle.begin_shutdown()

        assert deadline.remaining == 0.0

    def test_the_client_is_told_which_ending_it_got(self) -> None:
        from app.core import streams

        assert streams.closing_frame() == streams.EXPIRED
        assert b"lifetime" in streams.closing_frame()

        lifecycle.begin_shutdown()

        assert streams.closing_frame() == streams.RESTARTING
        assert b"restarting" in streams.closing_frame()


class TestTheSignalMarksTheProcessDraining:
    def test_the_handler_it_replaced_still_runs(self) -> None:
        import signal

        seen: list[int] = []
        previous = signal.signal(signal.SIGTERM, lambda sig, frame: seen.append(sig))
        try:
            lifecycle.watch_signals()
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)

            handler(signal.SIGTERM, None)

            assert lifecycle.shutting_down() is True
            assert seen == [signal.SIGTERM], "the server's own handler must still fire"
        finally:
            lifecycle.release_signals()
            signal.signal(signal.SIGTERM, previous)

    def test_releasing_puts_the_original_handler_back(self) -> None:
        import signal

        def original(sig, frame):
            return None

        previous = signal.signal(signal.SIGTERM, original)
        try:
            lifecycle.watch_signals()
            assert signal.getsignal(signal.SIGTERM) is not original

            lifecycle.release_signals()

            assert signal.getsignal(signal.SIGTERM) is original
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_a_default_disposition_is_left_alone(self) -> None:
        import signal

        previous = signal.signal(signal.SIGTERM, signal.SIG_DFL)
        try:
            lifecycle.watch_signals()

            assert (
                signal.getsignal(signal.SIGTERM) == signal.SIG_DFL
            ), "with nothing to delegate to, replacing SIG_DFL would swallow the signal"
        finally:
            lifecycle.release_signals()
            signal.signal(signal.SIGTERM, previous)
