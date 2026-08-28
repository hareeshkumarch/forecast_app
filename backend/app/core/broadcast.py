"""In-process fan-out, so a decision reaches a screen without being asked for.

Approving somebody happens on one person's screen and has to appear on
another's. Polling can only ever be late, and the interval is a choice between
a stale page and a query every few seconds from everybody who has the tab
open. This carries a nudge instead.

What travels is a topic name and nothing else. Subscribers respond by
refetching through the ordinary authenticated endpoint, which means the stream
cannot leak anything the reader was not already allowed to fetch, and a
subscription that outlives someone's access shows them nothing.

Single process, deliberately. The deployment this serves runs one uvicorn on
one instance — the production compose drops redis specifically to leave the
RAM for forecasting. A second API instance would need a real broker, and the
symptom would be quiet: everyone connected to the other instance stops
updating. `LOSES_EVENTS_ACROSS_PROCESSES` is here to be grepped for on the day
that matters.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

LOSES_EVENTS_ACROSS_PROCESSES = True

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


def publish(topic: str, event: str) -> int:
    delivered = 0
    for queue in tuple(_subscribers.get(topic, ())):
        try:
            queue.put_nowait(event)
            delivered += 1
        except asyncio.QueueFull:
            logger.debug("Dropping %s for a subscriber that is not reading.", topic)
    return delivered


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
