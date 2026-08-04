
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import RunStatus

logger = get_logger(__name__)

                                                                            
_QUEUE_MAXSIZE = 64


@dataclass(slots=True)
class ProgressEvent:
    run_id: uuid.UUID
    status: RunStatus
    progress: float
    stage: str
    message: str | None = None
    selected_model: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "status": self.status.value,
            "progress": round(self.progress, 4),
            "stage": self.stage,
            "message": self.message,
            "selected_model": self.selected_model,
            "error": self.error,
        }


@dataclass
class ProgressBus:

    _subscribers: dict[uuid.UUID, set[asyncio.Queue[ProgressEvent]]] = field(default_factory=dict)
                                                                              
                                                                
    _latest: dict[uuid.UUID, ProgressEvent] = field(default_factory=dict)

    def publish(self, event: ProgressEvent) -> None:
        self._latest[event.run_id] = event
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

    def forget(self, run_id: uuid.UUID) -> None:
        self._latest.pop(run_id, None)
        self._subscribers.pop(run_id, None)


progress_bus = ProgressBus()


class ExecutorRegistry:

    def __init__(self) -> None:
        self._executor: ProcessPoolExecutor | None = None

    def start(self) -> None:
        if self._executor is not None:
            return
        workers = max(1, settings.forecast_workers)
        self._executor = ProcessPoolExecutor(max_workers=workers)
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
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, func, *args)


executors = ExecutorRegistry()
