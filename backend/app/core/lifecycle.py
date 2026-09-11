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
    global _shutting_down_at
    _shutting_down_at = None
