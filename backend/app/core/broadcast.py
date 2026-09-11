from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

CHANNEL = "access:events"

ORIGIN = uuid.uuid4().hex

QUEUE_LIMIT = 8

ACCESS = "access"
PEOPLE = "people"

_subscribers: dict[str, set[asyncio.Queue[str]]] = defaultdict(set)


def topic_for_user(user_id: object) -> str:
    return f"{ACCESS}:{user_id}"


def deliver(topic: str, event: str) -> int:
    delivered = 0
    for queue in tuple(_subscribers.get(topic, ())):
        try:
            queue.put_nowait(event)
            delivered += 1
        except asyncio.QueueFull:
            logger.debug("Dropping %s for a subscriber that is not reading.", topic)
    return delivered


def publish(topic: str, event: str) -> int:
    delivered = deliver(topic, event)
    _announce_elsewhere(topic, event)
    return delivered


_client: Any | None = None
_in_flight: set[asyncio.Task[None]] = set()


def _announce_elsewhere(topic: str, event: str) -> None:
    if not settings.progress_channel_url:
        return
    payload = json.dumps({"origin": ORIGIN, "topic": topic, "event": event})
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_push_once(payload))
        return

    task = loop.create_task(_push(payload))
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)


async def _push(payload: str) -> None:
    try:
        await _redis().publish(CHANNEL, payload)
    except Exception:
        logger.warning("Could not announce an access change to other processes", exc_info=True)


async def _push_once(payload: str) -> None:
    client = _open()
    try:
        await client.publish(CHANNEL, payload)
    except Exception:
        logger.warning("Could not announce an access change to other processes", exc_info=True)
    finally:
        await client.aclose()


def _open() -> Any:
    import redis.asyncio as aioredis

    return aioredis.Redis.from_url(
        settings.progress_channel_url,
        socket_connect_timeout=3.0,
        health_check_interval=30,
    )


def _redis() -> Any:
    global _client
    if _client is None:
        _client = _open()
    return _client


class AccessRelay:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None or not settings.progress_channel_url:
            return
        self._task = asyncio.create_task(self._run(), name="access-relay")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        global _client
        if _client is not None:
            await _client.aclose()
            _client = None

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            client = _open()
            try:
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                await pubsub.subscribe(CHANNEL)
                logger.info("Relaying access changes from %s", CHANNEL)
                backoff = 1.0

                async for message in pubsub.listen():
                    _accept(message["data"])
            except asyncio.CancelledError:
                await client.aclose()
                raise
            except Exception:
                logger.warning("Access relay dropped; retrying in %.0fs", backoff, exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                await client.aclose()


def _accept(raw: str | bytes) -> None:
    try:
        frame = json.loads(raw)
        topic = str(frame["topic"])
        event = str(frame["event"])
        origin = str(frame.get("origin", ""))
    except (ValueError, KeyError, TypeError):
        logger.warning("Discarded a malformed access frame")
        return

    if origin == ORIGIN:
        return
    deliver(topic, event)


relay = AccessRelay()


@contextlib.asynccontextmanager
async def subscribe(*topics: str) -> AsyncIterator[asyncio.Queue[str]]:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_LIMIT)
    for topic in topics:
        _subscribers[topic].add(queue)
    try:
        yield queue
    finally:
        for topic in topics:
            remaining = _subscribers.get(topic)
            if remaining is None:
                continue
            remaining.discard(queue)
            if not remaining:
                del _subscribers[topic]


def subscriber_count(topic: str) -> int:
    return len(_subscribers.get(topic, ()))
