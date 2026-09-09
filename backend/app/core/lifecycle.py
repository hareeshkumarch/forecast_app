"""Whether this process is still willing to be sent work.

Liveness and readiness are different questions and were being answered by one
endpoint. "Is this process alive" stays true right up to the moment it exits —
answering false would have the supervisor restart something that is shutting
down on purpose. "Should this process be sent traffic" goes false the instant
a shutdown begins, which is what lets the load balancer take it out while the
forecasts already running are given time to land.

Answering both with `/api/health` meant a redeploy looked healthy while it was
already tearing down, so requests kept arriving at a process that could not
serve them.
"""

from __future__ import annotations

import time

_shutting_down_at: float | None = None


def begin_shutdown() -> None:
    global _shutting_down_at
    if _shutting_down_at is None:
        _shutting_down_at = time.monotonic()


def shutting_down() -> bool:
    return _shutting_down_at is not None


def draining_for() -> float:
    return 0.0 if _shutting_down_at is None else time.monotonic() - _shutting_down_at


def reset() -> None:
    """For tests. A real process shuts down once."""
    global _shutting_down_at
    _shutting_down_at = None
