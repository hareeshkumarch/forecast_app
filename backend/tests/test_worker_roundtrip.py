from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("CELERY_BROKER_URL"),
    reason="Set CELERY_BROKER_URL to exercise the worker round trip.",
)

WORKER_BOOT_TIMEOUT = 60
RUN_TIMEOUT = 240
FRAME_GRACE = 5
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _one_worker_only() -> None:
    if os.environ.get("PYTEST_XDIST_WORKER"):
        pytest.skip("Run this file with -n 0; parallel workers share one broker.")


@pytest.fixture(scope="module")
def worker(tmp_path_factory: pytest.TempPathFactory) -> Iterator[subprocess.Popen[bytes]]:
    assert os.environ.get("DATABASE_URL", "").startswith("sqlite"), "expected the test database"

    log_path = tmp_path_factory.mktemp("celery") / "worker.log"
    log = log_path.open("wb")

    def tail(limit: int = 4000) -> str:
        log.flush()
        return log_path.read_text(errors="replace")[-limit:]

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "--app=app.workers.celery_app.celery_app",
            "worker",
            "--loglevel=info",
            "--queues=forecasts",
            "--concurrency=1",
        ],
        cwd=BACKEND_ROOT,
        env={**os.environ},
        stdout=log,
        stderr=subprocess.STDOUT,
    )

    from app.workers.celery_app import celery_app

    try:
        deadline = time.monotonic() + WORKER_BOOT_TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(f"The worker exited before it was ready:\n{tail()}")
            if celery_app.control.ping(timeout=1.0):
                break
            time.sleep(1.0)
        else:
            process.send_signal(signal.SIGTERM)
            pytest.fail(f"The worker never became ready.\n{tail()}")

        yield process
    finally:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        print(f"\n--- celery worker log ({log_path}) ---\n{tail()}")
        log.close()


async def _seed_dataset() -> uuid.UUID:
    from app.database.sample_data import generate_csv_bytes
    from app.database.session import session_scope
    from app.services import dataset_service

    async with session_scope() as session:
        dataset, _profile = await dataset_service.create_from_upload(
            session, generate_csv_bytes(), "roundtrip.csv", name="Worker round trip"
        )
        return dataset.id


async def _dispatch_and_follow(
    dataset_id: uuid.UUID, **options: object
) -> tuple[object, list[dict]]:
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.database.session import session_scope
    from app.services import forecast_service
    from app.services.progress_relay import CHANNEL

    client = aioredis.Redis.from_url(settings.progress_channel_url)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(CHANNEL)

    async with session_scope() as session:
        run = await forecast_service.create_run(
            session,
            dataset_id=dataset_id,
            name="worker round trip",
            max_folds=2,
            horizon=3,
            **options,  # type: ignore[arg-type]
        )
        run_id = run.id
        await session.commit()
        await forecast_service.dispatch_run(session, run)

    frames: list[dict] = []

    async def collect() -> None:
        async for message in pubsub.listen():
            payload = json.loads(message["data"])
            if payload["run_id"] != str(run_id):
                continue
            frames.append(payload)
            if payload["status"] in ("completed", "failed"):
                return

    async def until_terminal_in_the_database() -> None:
        from app.models.enums import RunStatus

        terminal = {RunStatus.COMPLETED, RunStatus.FAILED}
        while True:
            await asyncio.sleep(1.0)
            async with session_scope() as session:
                row = await forecast_service.get_run(session, run_id)
            if row is not None and row.status in terminal:
                return

    collector = asyncio.create_task(collect())
    watcher = asyncio.create_task(until_terminal_in_the_database())
    try:
        done, pending = await asyncio.wait(
            {collector, watcher},
            timeout=RUN_TIMEOUT,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if watcher in done and collector not in done:
            await asyncio.wait({collector}, timeout=FRAME_GRACE)
        for task in pending | {collector, watcher}:
            if not task.done():
                task.cancel()
        if not done:
            raise TimeoutError(
                f"Run {run_id} neither published a terminal frame nor reached a "
                f"terminal status within {RUN_TIMEOUT}s."
            )
        for task in done:
            task.result()
    finally:
        await pubsub.aclose()
        await client.aclose()

    async with session_scope() as session:
        finished = await forecast_service.get_run(session, run_id)
        return finished, frames


def test_a_run_dispatched_to_a_worker_completes(worker: subprocess.Popen[bytes]) -> None:
    from app.models.enums import RunStatus
    from app.services.forecast_service import RunOverrides

    async def main() -> None:
        dataset_id = await _seed_dataset()
        run, frames = await _dispatch_and_follow(
            dataset_id, llm_api_key="sk-must-not-be-stored-in-the-clear"
        )

        assert run.status is RunStatus.COMPLETED, run.error_message
        assert run.selected_model is not None, "a completed run must name its winner"
        assert run.task_id, "the queued task id belongs on the run"

        stages = [frame["stage"] for frame in frames]
        assert "backtesting" in stages
        assert stages[-1] == "complete"

        assert len(frames) >= 4, stages

        stored = json.dumps(run.options)
        assert "sk-must-not-be-stored-in-the-clear" not in stored

        overrides = RunOverrides.from_stored(run.options)
        assert overrides.max_folds == 2
        assert overrides.llm_api_key == "sk-must-not-be-stored-in-the-clear"

    asyncio.run(main())


def test_a_grouped_run_fans_out_and_a_chord_closes_it(worker: subprocess.Popen[bytes]) -> None:
    from sqlalchemy import select

    from app.database.session import session_scope
    from app.models.entities import ForecastSeries
    from app.models.enums import RunStatus
    from app.services import forecast_service

    grain = ["region", "product_category"]

    async def main() -> None:
        dataset_id = await _seed_dataset()
        run, frames = await _dispatch_and_follow(dataset_id, group_by=grain)

        assert run.status is RunStatus.COMPLETED, run.error_message
        assert run.group_by == grain

        stages = [frame["stage"] for frame in frames]
        assert "fitting_series" in stages, stages
        assert stages[-1] == "complete"

        progress = [frame["progress"] for frame in frames]
        assert progress == sorted(progress), stages

        async with session_scope() as session:
            rows = list(
                (
                    await session.execute(
                        select(ForecastSeries).where(ForecastSeries.run_id == run.id)
                    )
                )
                .scalars()
                .all()
            )
            stored = await forecast_service.get_run(session, run.id)

        assert {row.level for row in rows} == {0, 1, 2}
        assert len([row for row in rows if row.level == 2]) == 25
        assert stored.series_count == len(rows)

        root = next(row for row in rows if row.level == 0)
        leaves = sum(row.forecast_total for row in rows if row.level == 2)
        assert leaves == pytest.approx(root.forecast_total, rel=1e-6)

        assert all(row.blocked_reason is None for row in rows), [
            (row.label, row.blocked_reason) for row in rows if row.blocked_reason
        ]

    asyncio.run(main())
