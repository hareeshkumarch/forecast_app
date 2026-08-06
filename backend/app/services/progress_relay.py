from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc  # noqa: UP017
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import RunStatus
from app.services.job_runner import ProgressEvent, progress_bus

logger = get_logger(__name__)

CHANNEL = "forecast:progress"

_publisher: Any | None = None
_publisher_retry_at = 0.0
_PUBLISHER_COOLDOWN_SECONDS = 5.0

_LATEST_TTL = 86_400

_PUBLISH_LATEST = """
local current = redis.call('GET', KEYS[1])
if current then
  local ok_old, old = pcall(cjson.decode, current)
  local ok_new, new = pcall(cjson.decode, ARGV[2])
  if ok_old and ok_new then
    local old_terminal = old.status == 'completed' or old.status == 'failed'
    local new_terminal = new.status == 'completed' or new.status == 'failed'
    local regresses = tonumber(new.progress) < tonumber(old.progress)
    local duplicate = tonumber(new.progress) == tonumber(old.progress)
      and tostring(new.updated_at or '') <= tostring(old.updated_at or '')
    if old_terminal or (not new_terminal and (regresses or duplicate)) then
      return 0
    end
  end
end
redis.call('SETEX', KEYS[1], ARGV[1], ARGV[2])
redis.call('PUBLISH', ARGV[3], ARGV[2])
return 1
"""


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
            updated_at=_aware(datetime.fromisoformat(payload["updated_at"]))
            if payload.get("updated_at")
            else datetime.now(UTC),
        )
    except (ValueError, KeyError, TypeError):
        logger.warning("Discarded a malformed progress frame")
        return None


def _client() -> Any:
    global _publisher
    if _publisher is None:
        import redis

        _publisher = redis.Redis.from_url(
            settings.progress_channel_url,
            socket_connect_timeout=1.0,
            socket_timeout=2.0,
            health_check_interval=30,
        )
    return _publisher


def _publisher_available() -> bool:
    return time.monotonic() >= _publisher_retry_at


def _publisher_failed() -> None:
    global _publisher_retry_at
    _publisher_retry_at = time.monotonic() + _PUBLISHER_COOLDOWN_SECONDS


def _publisher_recovered() -> None:
    global _publisher_retry_at
    _publisher_retry_at = 0.0


def publish_from_worker(event: ProgressEvent) -> None:
    if not settings.progress_channel_url:
        return
    if not _publisher_available() and event.status not in (RunStatus.COMPLETED, RunStatus.FAILED):
        return

    try:
        payload = json.dumps(event.to_dict())
        _client().eval(
            _PUBLISH_LATEST,
            1,
            _latest_key(event.run_id),
            _LATEST_TTL,
            payload,
            CHANNEL,
        )
        _publisher_recovered()
    except Exception:
        _publisher_failed()
        logger.warning("Could not publish progress for run %s", event.run_id, exc_info=True)


_COUNTER_TTL = 3_600


def _counter_key(run_id: uuid.UUID) -> str:
    return f"{CHANNEL}:{run_id}:series"


def _latest_key(run_id: uuid.UUID) -> str:
    return f"{CHANNEL}:{run_id}:latest"


async def latest_from_store(run_id: uuid.UUID) -> ProgressEvent | None:
    if not settings.progress_channel_url or not _publisher_available():
        return None
    try:
        raw = await asyncio.to_thread(_client().get, _latest_key(run_id))
        _publisher_recovered()
        return _decode(raw) if raw is not None else None
    except Exception:
        _publisher_failed()
        logger.warning("Could not restore progress for run %s", run_id, exc_info=True)
        return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def forget_progress(run_id: uuid.UUID) -> None:
    progress_bus.forget(run_id)
    if not settings.progress_channel_url:
        return
    try:
        await asyncio.to_thread(
            _client().delete,
            _latest_key(run_id),
            _counter_key(run_id),
        )
        _publisher_recovered()
    except Exception:
        _publisher_failed()
        logger.warning("Could not clear progress state for run %s", run_id, exc_info=True)


def count_series(run_id: uuid.UUID, done: int) -> int | None:
    if not settings.progress_channel_url or not _publisher_available():
        return None

    try:
        client = _client()
        total = int(client.incrby(_counter_key(run_id), done))
        client.expire(_counter_key(run_id), _COUNTER_TTL)
        _publisher_recovered()
        return total
    except Exception:
        _publisher_failed()
        logger.warning("Could not count series progress for run %s", run_id, exc_info=True)
        return None


def forget_series_count(run_id: uuid.UUID) -> None:
    if not settings.progress_channel_url:
        return
    try:
        _client().delete(_counter_key(run_id))
        _publisher_recovered()
    except Exception:
        _publisher_failed()
        logger.warning("Could not reset the series counter for run %s", run_id, exc_info=True)


class ProgressRelay:
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
            client = aioredis.Redis.from_url(
                settings.progress_channel_url,
                socket_connect_timeout=3.0,
                health_check_interval=30,
            )
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
