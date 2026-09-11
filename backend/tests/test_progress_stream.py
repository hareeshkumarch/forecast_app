from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import UTC
from app.database.sample_data import generate_csv_bytes
from app.models.enums import RunStatus
from app.services import dataset_service, forecast_service
from app.services.job_runner import (
    ProgressEvent,
    as_utc,
    executors,
    progress_bus,
    publish_progress,
)


@pytest.fixture
async def pool() -> AsyncIterator[None]:
    executors.shutdown()
    executors.start()
    yield
    executors.shutdown()


def _emit_from_worker(run_id: str, count: int) -> int:
    identifier = uuid.UUID(run_id)
    for index in range(count):
        publish_progress(
            ProgressEvent(
                run_id=identifier,
                status=RunStatus.RUNNING,
                progress=0.1 * (index + 1),
                stage="backtesting",
                message=f"model {index}",
            )
        )
    publish_progress(
        ProgressEvent(
            run_id=identifier,
            status=RunStatus.COMPLETED,
            progress=1.0,
            stage="complete",
            message="done",
        )
    )
    return os.getpid()


def _emit_junk_then_a_frame(run_id: str) -> int:
    identifier = uuid.UUID(run_id)
    from app.services import job_runner

    channel = job_runner._worker_channel
    assert channel is not None, "the initializer did not reach this worker"
    channel.put_nowait({"run_id": "not-a-uuid", "status": "running"})
    channel.put_nowait({"nothing": "useful"})
    publish_progress(
        ProgressEvent(
            run_id=identifier,
            status=RunStatus.COMPLETED,
            progress=1.0,
            stage="complete",
            message="survived",
        )
    )
    return os.getpid()


async def _until(condition: Callable[[], bool], *, within: float) -> bool:
    deadline = asyncio.get_running_loop().time() + within
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return condition()


async def _watch(run_id: uuid.UUID, sink: list[ProgressEvent]) -> asyncio.Task[None]:
    publish_progress(
        ProgressEvent(
            run_id=run_id,
            status=RunStatus.PENDING,
            progress=0.0,
            stage="queued",
            message="queued",
        )
    )

    async def watch() -> None:
        async for event in progress_bus.subscribe(run_id):
            sink.append(event)

    task = asyncio.create_task(watch())
    assert await _until(lambda: bool(sink), within=10), "the subscription never attached"
    return task


async def test_a_frame_published_in_a_worker_reaches_the_parent(pool: None) -> None:
    run_id = uuid.uuid4()
    seen: list[ProgressEvent] = []
    watcher = await _watch(run_id, seen)

    worker_pid = await executors.run(_emit_from_worker, str(run_id), 4)
    await asyncio.wait_for(watcher, timeout=60)

    assert worker_pid != os.getpid(), "this proves nothing unless it really was another process"
    assert [event.message for event in seen] == [
        "queued",
        "model 0",
        "model 1",
        "model 2",
        "model 3",
        "done",
    ]


async def test_the_frames_arrive_while_the_worker_is_still_running(pool: None) -> None:
    run_id = uuid.uuid4()
    seen: list[ProgressEvent] = []
    watcher = await _watch(run_id, seen)

    task = asyncio.ensure_future(executors.run(_emit_from_worker, str(run_id), 4))
    mid_flight = await _until(lambda: len(seen) >= 3, within=60)

    await task
    await asyncio.wait_for(watcher, timeout=60)
    assert mid_flight, "frames were still queued behind the worker's return"


async def test_a_malformed_frame_does_not_take_the_drain_down(pool: None) -> None:
    run_id = uuid.uuid4()
    seen: list[ProgressEvent] = []
    watcher = await _watch(run_id, seen)

    await executors.run(_emit_junk_then_a_frame, str(run_id))
    await asyncio.wait_for(watcher, timeout=60)

    assert [event.message for event in seen] == ["queued", "survived"]


async def test_the_drain_retires_on_shutdown(pool: None) -> None:
    drain = executors._drain
    assert drain is not None and drain.is_alive()

    executors.shutdown()
    drain.join(timeout=10)

    assert not drain.is_alive(), "a parked reader would outlive the pool it reads from"


def test_an_event_survives_a_round_trip_through_a_dict() -> None:
    event = ProgressEvent(
        run_id=uuid.uuid4(),
        status=RunStatus.RUNNING,
        progress=0.4213,
        stage="backtesting",
        message="Backtesting theta (3 of 8)...",
        selected_model="ensemble",
    )

    restored = ProgressEvent.from_dict(event.to_dict())

    assert restored.run_id == event.run_id
    assert restored.status is RunStatus.RUNNING
    assert restored.progress == pytest.approx(0.4213)
    assert restored.stage == "backtesting"
    assert restored.message == event.message
    assert restored.selected_model == "ensemble"
    assert restored.updated_at == event.updated_at


def test_a_naive_timestamp_is_read_as_utc() -> None:
    naive = datetime(2026, 8, 15, 12, 0, 0)
    assert as_utc(naive).tzinfo is UTC
    assert as_utc(naive.replace(tzinfo=UTC)) == naive.replace(tzinfo=UTC)


@pytest.mark.parametrize(
    "payload",
    [
        {"run_id": "not-a-uuid", "status": "running", "progress": 0, "stage": "x"},
        {"run_id": str(uuid.uuid4()), "status": "invented", "progress": 0, "stage": "x"},
        {},
    ],
)
def test_a_malformed_payload_is_rejected_rather_than_guessed_at(payload: dict) -> None:
    with pytest.raises((ValueError, KeyError, TypeError)):
        ProgressEvent.from_dict(payload)


def test_a_frame_that_goes_backwards_is_ignored() -> None:
    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    progress_bus.publish(ProgressEvent(run_id, RunStatus.RUNNING, 0.6, "fitting", updated_at=now))
    progress_bus.publish(
        ProgressEvent(
            run_id, RunStatus.RUNNING, 0.3, "backtesting", updated_at=now + timedelta(seconds=1)
        )
    )

    latest = progress_bus.latest(run_id)
    assert latest is not None and latest.progress == pytest.approx(0.6)
    progress_bus.forget(run_id)


def test_a_failure_still_lands_after_a_higher_percentage() -> None:
    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    progress_bus.publish(ProgressEvent(run_id, RunStatus.RUNNING, 0.9, "fitting", updated_at=now))
    progress_bus.publish(
        ProgressEvent(
            run_id,
            RunStatus.FAILED,
            0.4,
            "failed",
            error="ran out of history",
            updated_at=now + timedelta(seconds=1),
        )
    )

    latest = progress_bus.latest(run_id)
    assert latest is not None and latest.status is RunStatus.FAILED
    progress_bus.forget(run_id)


@pytest.mark.slow
async def test_a_real_run_reports_while_the_model_search_is_running(
    session: AsyncSession, pool: None
) -> None:
    dataset, _profile = await dataset_service.create_from_upload(
        session, generate_csv_bytes(), "panel.csv", name="Panel"
    )
    await session.commit()
    run = await forecast_service.create_run(session, dataset_id=dataset.id, horizon=3, max_folds=1)
    run_id = run.id
    await session.commit()

    seen: list[ProgressEvent] = []
    watcher = await _watch(run_id, seen)

    assert await forecast_service.execute_run(run_id) is RunStatus.COMPLETED
    await asyncio.wait_for(watcher, timeout=60)

    backtesting = [event for event in seen if event.stage == "backtesting"]
    assert len(backtesting) > 2, (
        "the model search reported only its start and end: "
        f"{[(event.stage, round(event.progress, 3)) for event in seen]}"
    )
    assert len({event.message for event in backtesting}) > 2
    assert backtesting[-1].progress > backtesting[0].progress

    percentages = [event.progress for event in seen]
    assert percentages == sorted(percentages), "progress never goes backwards"
    assert seen[-1].status is RunStatus.COMPLETED
