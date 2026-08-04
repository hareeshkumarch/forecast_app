"""
Proves a forecast survives the trip through a real broker and a real worker.

Everything else about the Celery path is unit-tested against fakes, which is
what let a nested process pool and a mislabelled task result reach the branch:
both only appear once an actual worker picks the job up. Skipped unless a
broker is configured, so the ordinary suite stays offline.
"""

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
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def worker() -> Iterator[subprocess.Popen[bytes]]:
    # conftest pins DATABASE_URL and STORAGE_ROOT to a temp directory before
    # anything imports settings, and the worker inherits both — so the two
    # processes genuinely share one database and one Parquet store.
    assert os.environ.get("DATABASE_URL", "").startswith("sqlite"), "expected the test database"

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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    from app.workers.celery_app import celery_app

    deadline = time.monotonic() + WORKER_BOOT_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read().decode() if process.stdout else ""
            pytest.fail(f"The worker exited before it was ready:\n{output[-2000:]}")
        if celery_app.control.ping(timeout=1.0):
            break
        time.sleep(1.0)
    else:
        process.send_signal(signal.SIGTERM)
        pytest.fail("The worker never became ready.")

    yield process

    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


async def _seed_dataset() -> uuid.UUID:
    from app.database.sample_data import generate_csv_bytes
    from app.database.session import session_scope
    from app.services import dataset_service

    async with session_scope() as session:
        dataset, _profile = await dataset_service.create_from_upload(
            session, generate_csv_bytes(), "roundtrip.csv", name="Worker round trip"
        )
        return dataset.id


async def _dispatch_and_follow(dataset_id: uuid.UUID) -> tuple[object, list[dict]]:
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
            llm_api_key="sk-must-not-be-stored-in-the-clear",
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

    try:
        await asyncio.wait_for(collect(), timeout=RUN_TIMEOUT)
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
        run, frames = await _dispatch_and_follow(dataset_id)

        assert run.status is RunStatus.COMPLETED, run.error_message
        assert run.selected_model is not None, "a completed run must name its winner"
        assert run.task_id, "the queued task id belongs on the run"

        # The pool the API uses cannot exist inside a daemonic worker, so a run
        # that gets past backtesting proves the fit happened inline.
        stages = [frame["stage"] for frame in frames]
        assert "backtesting" in stages
        assert stages[-1] == "complete"

        # Progress crossed a process boundary to get here.
        assert len(frames) >= 4, stages

        # The worker is a separate process, so the overrides only reached it
        # through the row — and the key had to survive that trip encrypted.
        stored = json.dumps(run.options)
        assert "sk-must-not-be-stored-in-the-clear" not in stored

        overrides = RunOverrides.from_stored(run.options)
        assert overrides.max_folds == 2
        assert overrides.llm_api_key == "sk-must-not-be-stored-in-the-clear"

    asyncio.run(main())
