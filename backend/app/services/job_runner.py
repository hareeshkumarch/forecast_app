from __future__ import annotations

import asyncio
import multiprocessing
import os
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc  # noqa: UP017
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import RunStatus

logger = get_logger(__name__)


_QUEUE_MAXSIZE = 64
_LATEST_MAXSIZE = 2_048


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(slots=True)
class ProgressEvent:
    run_id: uuid.UUID
    status: RunStatus
    progress: float
    stage: str
    message: str | None = None
    selected_model: str | None = None
    error: str | None = None
    queue_ahead: int | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "status": self.status.value,
            "progress": round(self.progress, 4),
            "stage": self.stage,
            "message": self.message,
            "selected_model": self.selected_model,
            "error": self.error,
            "queue_ahead": self.queue_ahead,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProgressEvent:
        raw_updated = payload.get("updated_at")
        return cls(
            run_id=uuid.UUID(str(payload["run_id"])),
            status=RunStatus(payload["status"]),
            progress=float(payload["progress"]),
            stage=str(payload["stage"]),
            message=payload.get("message"),
            selected_model=payload.get("selected_model"),
            error=payload.get("error"),
            queue_ahead=(
                int(payload["queue_ahead"]) if payload.get("queue_ahead") is not None else None
            ),
            updated_at=as_utc(datetime.fromisoformat(raw_updated))
            if raw_updated
            else datetime.now(UTC),
        )


@dataclass
class ProgressBus:
    _subscribers: dict[uuid.UUID, set[asyncio.Queue[ProgressEvent]]] = field(default_factory=dict)

    _latest: dict[uuid.UUID, ProgressEvent] = field(default_factory=dict)

    def publish(self, event: ProgressEvent) -> None:
        current = self._latest.get(event.run_id)
        if current is not None:
            terminal = (RunStatus.COMPLETED, RunStatus.FAILED)
            if current.status in terminal:
                return
            if event.status not in terminal and (
                event.progress < current.progress or event.updated_at <= current.updated_at
            ):
                logger.debug("Ignored an out-of-order progress frame for run %s", event.run_id)
                return
        self._latest.pop(event.run_id, None)
        self._latest[event.run_id] = event
        self._trim_latest()
        for queue in list(self._subscribers.get(event.run_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    logger.debug("Dropped a progress frame for run %s", event.run_id)

    def latest(self, run_id: uuid.UUID) -> ProgressEvent | None:
        return self._latest.get(run_id)

    async def subscribe(self, run_id: uuid.UUID) -> AsyncGenerator[ProgressEvent, None]:
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers.setdefault(run_id, set()).add(queue)

        try:
            replay = self._latest.get(run_id)
            if replay is not None:
                yield replay
                if replay.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                    return

            while True:
                event = await queue.get()
                yield event
                if event.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                    return
        finally:
            subscribers = self._subscribers.get(run_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(run_id, None)
            self._trim_latest()

    def forget(self, run_id: uuid.UUID) -> None:
        self._latest.pop(run_id, None)
        self._subscribers.pop(run_id, None)

    def _trim_latest(self) -> None:
        if len(self._latest) <= _LATEST_MAXSIZE:
            return
        terminal = (RunStatus.COMPLETED, RunStatus.FAILED)
        for run_id, event in list(self._latest.items()):
            if len(self._latest) <= _LATEST_MAXSIZE:
                break
            if event.status in terminal and not self._subscribers.get(run_id):
                self._latest.pop(run_id, None)


progress_bus = ProgressBus()


_worker_channel: Any | None = None


_STOP = None


_BLAS_THREAD_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def _pin_blas_threads() -> None:
    threads = max(1, settings.forecast_blas_threads)
    for name in _BLAS_THREAD_VARS:
        os.environ.setdefault(name, str(threads))


def _adopt_channel(channel: Any) -> None:
    global _worker_channel
    _pin_blas_threads()
    _worker_channel = channel


def _deliver(payload: dict[str, Any]) -> None:
    try:
        progress_bus.publish(ProgressEvent.from_dict(payload))
    except Exception:
        logger.debug("Discarded a malformed progress frame from a worker", exc_info=True)


def publish_progress(event: ProgressEvent) -> None:
    progress_bus.publish(event)

    if _worker_channel is not None:
        try:
            _worker_channel.put_nowait(event.to_dict())
        except Exception:
            logger.debug("Could not forward progress to the parent", exc_info=True)

    if settings.distributed:
        try:
            from celery import current_task

            task_id = getattr(getattr(current_task, "request", None), "id", None)
            if task_id:
                current_task.update_state(state="PROGRESS", meta=event.to_dict())
        except Exception:
            logger.debug("Could not update Celery progress metadata", exc_info=True)

    if settings.progress_channel_url:
        from app.services.progress_relay import publish_from_worker

        publish_from_worker(event)


MODEL_SEARCH = "model"
SERIES_CHUNK = "series"


class ShuttingDown(RuntimeError): ...


@dataclass(slots=True)
class Waiting:
    run_id: uuid.UUID
    kind: str
    queued_at: float
    sequence: int
    admitted: asyncio.Future[None]


@dataclass(frozen=True, slots=True)
class SlotSnapshot:
    run_id: uuid.UUID
    running: int
    waiting: int
    ahead: int
    waiting_since: float | None


class Scheduler:
    def __init__(self) -> None:
        self._slots = 0
        self._held: dict[uuid.UUID, int] = {}
        self._waiting: list[Waiting] = []
        self._sequence = 0
        self._closed = False

    @property
    def slots(self) -> int:
        return self._slots or max(1, settings.forecast_workers)

    @property
    def running(self) -> int:
        return sum(self._held.values())

    @property
    def queued(self) -> int:
        return len(self._waiting)

    def _ahead_of(self, waiter: Waiting) -> int:
        return sum(1 for other in self._waiting if other.sequence < waiter.sequence)

    def snapshot(self) -> list[SlotSnapshot]:
        runs = set(self._held) | {waiter.run_id for waiter in self._waiting}
        rows = []
        for run_id in runs:
            mine = [waiter for waiter in self._waiting if waiter.run_id == run_id]
            first = min(mine, key=lambda waiter: waiter.sequence, default=None)
            rows.append(
                SlotSnapshot(
                    run_id=run_id,
                    running=self._held.get(run_id, 0),
                    waiting=len(mine),
                    ahead=self._ahead_of(first) if first is not None else 0,
                    waiting_since=first.queued_at if first is not None else None,
                )
            )
        return sorted(rows, key=lambda row: (-row.running, row.ahead))

    def position_of(self, run_id: uuid.UUID) -> int | None:
        mine = [waiter for waiter in self._waiting if waiter.run_id == run_id]
        if not mine:
            return None
        return self._ahead_of(min(mine, key=lambda waiter: waiter.sequence))

    async def acquire(
        self,
        run_id: uuid.UUID,
        kind: str,
        on_wait: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        if self._closed:
            raise ShuttingDown(
                "This server is restarting and is not starting new model work. The run is "
                "retryable and will say so."
            )

        if not self._waiting and self.running < self.slots:
            self._held[run_id] = self._held.get(run_id, 0) + 1
            return

        self._sequence += 1
        waiter = Waiting(
            run_id=run_id,
            kind=kind,
            queued_at=time.monotonic(),
            sequence=self._sequence,
            admitted=asyncio.get_running_loop().create_future(),
        )
        self._waiting.append(waiter)
        _announce_wait(self)
        if on_wait is not None:
            await on_wait(self._ahead_of(waiter))

        try:
            await waiter.admitted
        except asyncio.CancelledError:
            if waiter in self._waiting:
                self._waiting.remove(waiter)
            elif waiter.admitted.done() and not waiter.admitted.cancelled():
                self._release(run_id)
            raise

    def release(self, run_id: uuid.UUID) -> None:
        self._release(run_id)

    def _release(self, run_id: uuid.UUID) -> None:
        remaining = self._held.get(run_id, 0) - 1
        if remaining > 0:
            self._held[run_id] = remaining
        else:
            self._held.pop(run_id, None)
        self._promote()

    def _promote(self) -> None:
        promoted = False
        while self._waiting and self.running < self.slots:
            waiter = min(
                self._waiting,
                key=lambda item: (self._held.get(item.run_id, 0), item.sequence),
            )
            self._waiting.remove(waiter)
            if waiter.admitted.done():
                continue
            self._held[waiter.run_id] = self._held.get(waiter.run_id, 0) + 1
            waiter.admitted.set_result(None)
            promoted = True
        if promoted or self._waiting:
            _announce_wait(self)

    def close(self) -> None:
        self._closed = True
        for waiter in self._waiting:
            if not waiter.admitted.done():
                waiter.admitted.cancel()
        self._waiting.clear()

    @property
    def closed(self) -> bool:
        return self._closed

    def forget_all(self) -> None:
        for waiter in self._waiting:
            if not waiter.admitted.done():
                waiter.admitted.cancel()
        self._waiting.clear()
        self._held.clear()
        self._closed = False


scheduler = Scheduler()


announce_wait: Any | None = None


def _announce_wait(current: Scheduler) -> None:
    if announce_wait is None:
        return
    seen: set[uuid.UUID] = set()
    for waiter in current._waiting:
        if waiter.kind != MODEL_SEARCH or waiter.run_id in seen:
            continue
        seen.add(waiter.run_id)
        try:
            announce_wait(waiter.run_id, current._ahead_of(waiter), current.slots)
        except Exception:
            logger.debug("Could not announce a queue position", exc_info=True)


def _in_daemonic_process() -> bool:
    return bool(multiprocessing.current_process().daemon)


class ExecutorRegistry:
    def __init__(self) -> None:
        self._executor: ProcessPoolExecutor | None = None
        self._channel: Any | None = None
        self._drain: threading.Thread | None = None

    @property
    def inline(self) -> bool:
        return settings.distributed or _in_daemonic_process()

    def start(self) -> None:
        if self._executor is not None or self.inline:
            return
        workers = max(1, settings.forecast_workers)
        context = multiprocessing.get_context("spawn")
        self._channel = context.Queue(maxsize=_QUEUE_MAXSIZE * workers)
        self._executor = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_adopt_channel,
            initargs=(self._channel,),
        )
        logger.info("Started forecast process pool with %d worker(s).", workers)
        self.start_relay()

    def start_relay(self) -> None:
        if self._channel is None or self._drain is not None:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        channel = self._channel

        def pump() -> None:
            while True:
                try:
                    payload = channel.get()
                except (OSError, ValueError, EOFError):
                    return
                if payload is _STOP:
                    return
                try:
                    loop.call_soon_threadsafe(_deliver, payload)
                except RuntimeError:
                    return

        self._drain = threading.Thread(target=pump, name="progress-drain", daemon=True)
        self._drain.start()
        logger.info("Relaying worker progress into this process.")

    async def drain(self, seconds: float) -> int:
        if seconds <= 0 or self.inline:
            return scheduler.running

        scheduler.close()
        deadline = time.monotonic() + seconds
        while scheduler.running > 0 and time.monotonic() < deadline:
            logger.info(
                "Waiting for %d forecast(s) to finish before shutting down (%.0fs left).",
                scheduler.running,
                deadline - time.monotonic(),
            )
            await asyncio.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
        return scheduler.running

    def shutdown(self) -> None:
        channel, self._channel = self._channel, None
        if channel is not None:
            try:
                channel.put_nowait(_STOP)
            except Exception:
                logger.debug("Could not signal the progress drain", exc_info=True)
        self._drain = None
        if self._executor is None:
            return
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._executor = None
        logger.info("Forecast process pool shut down.")

    @property
    def executor(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self.start()
        assert self._executor is not None
        return self._executor

    async def run(self, func: Any, *args: Any) -> Any:
        if self.inline:
            return func(*args)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, func, *args)

    async def run_for(
        self,
        run_id: uuid.UUID,
        kind: str,
        func: Any,
        *args: Any,
        on_wait: Callable[[int], Awaitable[None]] | None = None,
        on_start: Callable[[], Awaitable[None]] | None = None,
    ) -> Any:
        if self.inline:
            if on_start is not None:
                await on_start()
            return func(*args)

        await scheduler.acquire(run_id, kind, on_wait)
        try:
            if on_start is not None:
                await on_start()
            return await self.run(func, *args)
        finally:
            scheduler.release(run_id)


executors = ExecutorRegistry()
