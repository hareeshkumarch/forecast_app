from __future__ import annotations

import asyncio
import multiprocessing
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import RunStatus

logger = get_logger(__name__)


_QUEUE_MAXSIZE = 64
_LATEST_MAXSIZE = 2_048


@dataclass(slots=True)
class ProgressEvent:
    run_id: uuid.UUID
    status: RunStatus
    progress: float
    stage: str
    message: str | None = None
    selected_model: str | None = None
    error: str | None = None
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
            "updated_at": self.updated_at.isoformat(),
        }


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
        # Reinsert so dictionary order is an inexpensive LRU clock.
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

    async def subscribe(self, run_id: uuid.UUID) -> AsyncIterator[ProgressEvent]:
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
        """Bounds terminal snapshots without evicting active subscriptions."""
        if len(self._latest) <= _LATEST_MAXSIZE:
            return
        terminal = (RunStatus.COMPLETED, RunStatus.FAILED)
        for run_id, event in list(self._latest.items()):
            if len(self._latest) <= _LATEST_MAXSIZE:
                break
            if event.status in terminal and not self._subscribers.get(run_id):
                self._latest.pop(run_id, None)


progress_bus = ProgressBus()


def publish_progress(event: ProgressEvent) -> None:
    """
    The single way progress leaves the code that produces it. In-process
    subscribers always see it; with Redis configured it is also fanned out so a
    stream served by another process — or another API instance — sees it too.
    """
    progress_bus.publish(event)

    if settings.distributed:
        try:
            from celery import current_task

            task_id = getattr(getattr(current_task, "request", None), "id", None)
            if task_id:
                current_task.update_state(state="PROGRESS", meta=event.to_dict())
        except Exception:
            # The application stream and durable snapshot remain authoritative;
            # Celery's own result metadata is useful for operators, not a reason
            # to fail a forecast.
            logger.debug("Could not update Celery progress metadata", exc_info=True)

    if settings.progress_channel_url:
        from app.services.progress_relay import publish_from_worker

        publish_from_worker(event)


def _in_daemonic_process() -> bool:
    """
    A Celery prefork worker is daemonic and cannot spawn children, so a nested
    pool is impossible there — and pointless, because the worker process is
    already the isolation boundary the pool exists to provide.
    """
    return bool(multiprocessing.current_process().daemon)


class ExecutorRegistry:
    def __init__(self) -> None:
        self._executor: ProcessPoolExecutor | None = None

    @property
    def inline(self) -> bool:
        return settings.distributed or _in_daemonic_process()

    def start(self) -> None:
        if self._executor is not None or self.inline:
            return
        workers = max(1, settings.forecast_workers)
        self._executor = ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn")
        )
        logger.info("Started forecast process pool with %d worker(s).", workers)

    def shutdown(self) -> None:
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
            # Already inside a worker dedicated to this one run: fit here and
            # let the worker's own concurrency provide the parallelism.
            return func(*args)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, func, *args)


executors = ExecutorRegistry()
