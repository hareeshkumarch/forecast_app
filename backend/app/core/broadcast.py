"""In-process fan-out, so a decision reaches a screen without being asked for.

Approving somebody happens on one person's screen and has to appear on
another's. Polling can only ever be late, and the interval is a choice between
a stale page and a query every few seconds from everybody who has the tab
open. This carries a nudge instead.

What travels is a topic name and nothing else. Subscribers respond by
refetching through the ordinary authenticated endpoint, which means the stream
cannot leak anything the reader was not already allowed to fetch, and a
subscription that outlives someone's access shows them nothing.

In-process when there is nothing else, and across processes when there is.
The deployment this serves runs one uvicorn on one instance — the production
compose drops redis specifically to leave the RAM for forecasting — and on
that shape the dictionary below is the whole mechanism. Add a second API
instance and the failure used to be silent: a decision made on the instance
you are not connected to never reaches your screen, and the page sits there
looking like it is working. Where a Redis is configured the nudge now also
goes out on a channel and comes back in on every other process, which is the
same bridge the forecast progress relay already crosses.

What travels between processes is still a topic name and nothing else.
"""

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

#: The channel other API processes are listening on. Named apart from the
#: progress channel so a subscriber never has to sort one kind from the other.
CHANNEL = "access:events"

#: This process, so it can recognise and drop the echo of its own publish —
#: which a local subscriber has already been handed directly.
ORIGIN = uuid.uuid4().hex

#: A subscriber that has not been read from is a browser that went away
#: without closing the connection. Eight is far more than the two or three a
#: live page could be behind, so hitting it means nobody is listening and the
#: right thing is to drop the nudge rather than grow a queue forever.
QUEUE_LIMIT = 8

ACCESS = "access"
PEOPLE = "people"

_subscribers: dict[str, set[asyncio.Queue[str]]] = defaultdict(set)


def topic_for_user(user_id: object) -> str:
    return f"{ACCESS}:{user_id}"


def deliver(topic: str, event: str) -> int:
    """Hand a nudge to the subscribers in this process, and nowhere else."""
    delivered = 0
    for queue in tuple(_subscribers.get(topic, ())):
        try:
            queue.put_nowait(event)
            delivered += 1
        except asyncio.QueueFull:
            logger.debug("Dropping %s for a subscriber that is not reading.", topic)
    return delivered


def publish(topic: str, event: str) -> int:
    """Deliver here, and — where there is somewhere else — announce it there too.

    The return value counts this process's subscribers only. It is what the
    tests assert on and what a caller can actually know; how many screens are
    attached to another instance is not answerable from here.
    """
    delivered = deliver(topic, event)
    _announce_elsewhere(topic, event)
    return delivered


_client: Any | None = None
#: Tasks are only weakly referenced by the loop, so one dropped here is one
#: the garbage collector may cancel before it has published anything.
_in_flight: set[asyncio.Task[None]] = set()


def _announce_elsewhere(topic: str, event: str) -> None:
    if not settings.progress_channel_url:
        return
    payload = json.dumps({"origin": ORIGIN, "topic": topic, "event": event})
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop: a script, or a worker process. The pooled client below
        # belongs to whichever loop opened it, so a one-shot connection is used
        # here rather than one that would be dead by the next call.
        asyncio.run(_push_once(payload))
        return

    task = loop.create_task(_push(payload))
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)


async def _push(payload: str) -> None:
    try:
        await _redis().publish(CHANNEL, payload)
    except Exception:
        # A nudge is an optimisation over the polling the clients still do, so
        # losing one costs latency rather than correctness.
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
    """Nudges from the other API processes, delivered into this one."""

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

    # Our own publish, come back around. The local subscribers already have it.
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
            # Left in place an empty set per topic accumulates one entry per
            # account that has ever connected, which on a long-running process
            # is a slow leak keyed by user id.
            if not remaining:
                del _subscribers[topic]


def subscriber_count(topic: str) -> int:
    return len(_subscribers.get(topic, ()))
