from __future__ import annotations

import asyncio
import contextlib
import signal
import threading
import time
from collections.abc import Callable
from types import FrameType

_shutting_down_at: float | None = None

_SIGNALS = (signal.SIGINT, signal.SIGTERM)

_chained: dict[int, Callable[[int, FrameType | None], None]] = {}

_drain_event: asyncio.Event | None = None
_drain_loop: asyncio.AbstractEventLoop | None = None


def drain_event() -> asyncio.Event:
    """An event that fires the moment a shutdown begins.

    A stream already blocked on a long keepalive wait cannot see a flag; it needs
    something to wake it, or it holds the shutdown open until the wait elapses.
    """
    global _drain_event, _drain_loop
    loop = asyncio.get_running_loop()
    if _drain_event is None or _drain_loop is not loop:
        _drain_event = asyncio.Event()
        _drain_loop = loop
    if _shutting_down_at is not None:
        _drain_event.set()
    return _drain_event


def begin_shutdown() -> None:
    global _shutting_down_at
    if _shutting_down_at is not None:
        return
    _shutting_down_at = time.monotonic()

    event, loop = _drain_event, _drain_loop
    if event is None or loop is None:
        return
    if loop.is_running():
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(event.set)
    else:
        event.set()


def shutting_down() -> bool:
    return _shutting_down_at is not None


def draining_for() -> float:
    return 0.0 if _shutting_down_at is None else time.monotonic() - _shutting_down_at


def _ahead_of(
    previous: Callable[[int, FrameType | None], None],
) -> Callable[[int, FrameType | None], None]:
    def handler(sig: int, frame: FrameType | None) -> None:
        begin_shutdown()
        previous(sig, frame)

    return handler


def watch_signals() -> None:
    """Mark the process draining at the signal rather than at lifespan shutdown.

    Uvicorn waits for every open connection before it runs lifespan shutdown, so
    a flag set there is set too late to close the streams that are holding it up.
    """
    if threading.current_thread() is not threading.main_thread():
        return

    for sig in _SIGNALS:
        with contextlib.suppress(ValueError, OSError):
            previous = signal.getsignal(sig)
            if not callable(previous) or sig in _chained:
                continue
            signal.signal(sig, _ahead_of(previous))
            _chained[sig] = previous


def release_signals() -> None:
    while _chained:
        sig, previous = _chained.popitem()
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, previous)


def reset() -> None:
    global _shutting_down_at, _drain_event, _drain_loop
    _shutting_down_at = None
    _drain_event = None
    _drain_loop = None
    release_signals()
