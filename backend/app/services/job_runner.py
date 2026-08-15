from __future__ import annotations

import asyncio
import multiprocessing
import threading
import uuid
from collections.abc import AsyncGenerator
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
    """Treat a naive timestamp as UTC.

    Progress frames are ordered by `updated_at`, and a naive value read back
    from Postgres would otherwise be incomparable with an aware one produced
    in a worker.
    """
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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProgressEvent:
        """Rebuild an event written by `to_dict`.

        Every route a frame can take between processes — the worker pipe, the
        Redis channel — ends here, so there is one definition of what the wire
        format is. Raises on anything malformed; callers decide whether a bad
        frame is worth a log line.
        """
        raw_updated = payload.get("updated_at")
        return cls(
            run_id=uuid.UUID(str(payload["run_id"])),
            status=RunStatus(payload["status"]),
            progress=float(payload["progress"]),
            stage=str(payload["stage"]),
            message=payload.get("message"),
            selected_model=payload.get("selected_model"),
            error=payload.get("error"),
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


#: Set in a pool worker, by the initializer below. In the parent it stays None.
#:
#: Without it a worker's progress has nowhere to go in the single-node
#: configuration. `progress_bus` is a module-level object, so the copy a
#: worker publishes to is its own; the Celery branch needs a broker and the
#: relay branch needs Redis, and this deployment runs neither. Every
#: fine-grained event the engine emits — one per candidate model, roughly
#: sixteen across a backtest — was therefore written into a bus nobody reads,
#: and a run appeared to freeze at whatever coarse percentage the parent had
#: last set for itself.
_worker_channel: Any | None = None


#: Put on the channel to retire the drain thread. It has to be `None` rather
#: than a sentinel object: everything on the channel is pickled and rebuilt on
#: the way through, and `None` is the only value whose identity survives that.
#: Frames are always dicts, so there is nothing to confuse it with.
_STOP = None


def _adopt_channel(channel: Any) -> None:
    """Pool initializer: hand each worker the pipe back to the parent."""
    global _worker_channel
    _worker_channel = channel


def _deliver(payload: dict[str, Any]) -> None:
    """Publish a worker's frame on the event loop that owns the subscribers."""
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
            # A full queue means the parent is behind, and progress is the
            # most droppable thing in the system — the run itself is
            # unaffected, and the next event supersedes this one anyway.
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
        # Bounded: progress is the one thing worth dropping under pressure, and
        # an unbounded queue would let a stalled parent grow without limit.
        self._channel = context.Queue(maxsize=_QUEUE_MAXSIZE * workers)
        self._executor = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_adopt_channel,
            initargs=(self._channel,),
        )
        logger.info("Started forecast process pool with %d worker(s).", workers)
        # Attached here rather than only from the app's lifespan, so a pool the
        # `executor` property creates on demand cannot end up without a reader
        # — which is the same silent hole this whole mechanism closes.
        self.start_relay()

    def start_relay(self) -> None:
        """Drain worker progress into this process's bus.

        The queue's `get` blocks, so it is read on a thread of its own rather
        than on the default executor — that pool is shared with every
        `asyncio.to_thread` call in the app, and this reader parks for the
        life of the process. What crosses back to the loop is a finished dict.
        """
        if self._channel is None or self._drain is not None:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop: a script or a Celery worker, where nothing is
            # subscribed in this process anyway.
            return
        channel = self._channel

        def pump() -> None:
            while True:
                try:
                    payload = channel.get()
                except (OSError, ValueError, EOFError):  # channel closed on shutdown
                    return
                if payload is _STOP:
                    return
                try:
                    loop.call_soon_threadsafe(_deliver, payload)
                except RuntimeError:  # the loop is gone; so is anyone listening
                    return

        self._drain = threading.Thread(target=pump, name="progress-drain", daemon=True)
        self._drain.start()
        logger.info("Relaying worker progress into this process.")

    def shutdown(self) -> None:
        channel, self._channel = self._channel, None
        if channel is not None:
            # The drain thread is parked on a blocking get, and closing the
            # queue underneath it is not guaranteed to wake it. A sentinel is.
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


executors = ExecutorRegistry()
