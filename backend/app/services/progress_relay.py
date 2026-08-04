from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import RunStatus
from app.services.job_runner import ProgressEvent, progress_bus

logger = get_logger(__name__)

CHANNEL = "forecast:progress"
LATEST_KEY = "forecast:progress:latest"
LATEST_TTL_SECONDS = 3_600


def _decode(raw: str | bytes) -> ProgressEvent | None:
    try:
        payload = json.loads(raw)
        return ProgressEvent(
            run_id=uuid.UUID(payload["run_id"]),
            status=RunStatus(payload["status"]),
            progress=float(payload["progress"]),
            stage=str(payload["stage"]),
            message=payload.get("message"),
            selected_model=payload.get("selected_model"),
            error=payload.get("error"),
        )
    except (ValueError, KeyError, TypeError):
        logger.warning("Discarded a malformed progress frame")
        return None


def publish_from_worker(event: ProgressEvent) -> None:
    """
    Called from the Celery worker, which has no event loop of its own. Also
    keeps the last frame under a key so a stream that connects mid-run opens
    with the current state rather than silence.
    """
    if not settings.progress_channel_url:
        return

    import redis

    payload = json.dumps(event.to_dict())
    try:
        client = redis.Redis.from_url(settings.progress_channel_url)
        pipeline = client.pipeline()
        pipeline.publish(CHANNEL, payload)
        pipeline.hset(LATEST_KEY, str(event.run_id), payload)
        pipeline.expire(LATEST_KEY, LATEST_TTL_SECONDS)
        pipeline.execute()
    except Exception:
        # Progress is advisory: the run itself must not fail because the
        # stream is unavailable.
        logger.warning("Could not publish progress for run %s", event.run_id, exc_info=True)


async def latest_from_redis(run_id: uuid.UUID) -> ProgressEvent | None:
    if not settings.progress_channel_url:
        return None

    import redis.asyncio as aioredis

    client = aioredis.Redis.from_url(settings.progress_channel_url)
    try:
        raw = await client.hget(LATEST_KEY, str(run_id))
        return _decode(raw) if raw else None
    except Exception:
        logger.warning("Could not read the last progress frame for run %s", run_id)
        return None
    finally:
        await client.aclose()


class ProgressRelay:
    """
    Bridges Redis pub/sub into the in-process bus, so an SSE stream served by
    any API instance sees progress published by any worker. Runs for the life
    of the application; without a Redis URL it is a no-op and the in-process
    bus serves single-node deployments unchanged.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None or not settings.progress_channel_url:
            return
        self._task = asyncio.create_task(self._run(), name="progress-relay")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        import redis.asyncio as aioredis

        backoff = 1.0
        while True:
            client = aioredis.Redis.from_url(settings.progress_channel_url)
            try:
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                await pubsub.subscribe(CHANNEL)
                logger.info("Relaying forecast progress from %s", CHANNEL)
                backoff = 1.0

                async for message in pubsub.listen():
                    event = _decode(message["data"])
                    if event is not None:
                        progress_bus.publish(event)
            except asyncio.CancelledError:
                await client.aclose()
                raise
            except Exception:
                logger.warning("Progress relay dropped; retrying in %.0fs", backoff, exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                await client.aclose()


relay = ProgressRelay()
