from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

import httpx

from app.core import metrics
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class BreakerState(StrEnum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


_STATE_VALUE = {BreakerState.CLOSED: 0.0, BreakerState.HALF_OPEN: 1.0, BreakerState.OPEN: 2.0}

_TRANSPORT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504, 507, 509, 522, 524})


class CircuitOpenError(AppError):
    status_code = 503
    code = "upstream_unavailable"


def is_transport_failure(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSPORT_STATUSES
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
        return True
    return isinstance(exc, TimeoutError | ConnectionError | OSError)


@dataclass(frozen=True, slots=True)
class BreakerSnapshot:
    name: str
    state: BreakerState
    consecutive_failures: int
    opened_at: float | None
    retry_after_seconds: int

    @property
    def healthy(self) -> bool:
        return self.state is BreakerState.CLOSED


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 4,
        reset_timeout_seconds: float = 30.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("A breaker needs at least one failure before it can open.")
        if reset_timeout_seconds <= 0:
            raise ValueError("A breaker's cooldown must be positive.")

        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds

        self._lock = threading.Lock()
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_started_at: float | None = None
        metrics.breaker_state.set(_STATE_VALUE[BreakerState.CLOSED], breaker=name)

    @property
    def state(self) -> BreakerState:
        with self._lock:
            return self._transition(time.monotonic())

    def snapshot(self) -> BreakerSnapshot:
        with self._lock:
            now = time.monotonic()
            state = self._transition(now)
            return BreakerSnapshot(
                name=self.name,
                state=state,
                consecutive_failures=self._failures,
                opened_at=self._opened_at,
                retry_after_seconds=self._retry_after(now),
            )

    def _retry_after(self, now: float) -> int:
        if self._state is not BreakerState.OPEN or self._opened_at is None:
            return 0
        return max(1, int(self._opened_at + self.reset_timeout_seconds - now) + 1)

    def _transition(self, now: float) -> BreakerState:
        if (
            self._state is BreakerState.OPEN
            and self._opened_at is not None
            and now - self._opened_at >= self.reset_timeout_seconds
        ):
            self._set(BreakerState.HALF_OPEN)
            self._trial_started_at = None
        return self._state

    def _set(self, state: BreakerState) -> None:
        if state is not self._state:
            logger.info("circuit breaker %s: %s -> %s", self.name, self._state, state)
            metrics.breaker_events.inc(breaker=self.name, event=str(state))
        self._state = state
        metrics.breaker_state.set(_STATE_VALUE[state], breaker=self.name)

    def allows(self) -> bool:
        with self._lock:
            now = time.monotonic()
            state = self._transition(now)
            if state is BreakerState.CLOSED:
                return True
            if state is BreakerState.OPEN or self._trial_claimed(now):
                metrics.breaker_events.inc(breaker=self.name, event="refused")
                return False
            self._trial_started_at = now
            return True

    def _trial_claimed(self, now: float) -> bool:
        if self._trial_started_at is None:
            return False
        if now - self._trial_started_at >= self.reset_timeout_seconds:
            logger.warning(
                "circuit breaker %s: a half-open trial never reported back; releasing it.",
                self.name,
            )
            self._trial_started_at = None
            return False
        return True

    def release_trial(self) -> None:
        with self._lock:
            self._trial_started_at = None

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._trial_started_at = None
            self._set(BreakerState.CLOSED)

    def record_failure(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._failures += 1
            self._trial_started_at = None
            if self._state is BreakerState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._opened_at = now
                self._set(BreakerState.OPEN)

    def reset(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._trial_started_at = None
            self._set(BreakerState.CLOSED)

    def call(self, fn: Callable[[], T]) -> T:
        if not self.allows():
            snapshot = self.snapshot()
            raise CircuitOpenError(
                f"{self.name} is unavailable right now. Recent calls to it failed, so this "
                "request was refused immediately rather than left to time out.",
                detail={
                    "dependency": self.name,
                    "retry_after_seconds": snapshot.retry_after_seconds,
                },
            )
        try:
            result = fn()
        except BaseException as exc:
            if is_transport_failure(exc):
                self.record_failure()
            else:
                self.record_success()
            raise
        else:
            self.record_success()
            return result


_REGISTRY: dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK = threading.Lock()


def breaker(
    name: str, *, failure_threshold: int = 4, reset_timeout_seconds: float = 30.0
) -> CircuitBreaker:
    with _REGISTRY_LOCK:
        existing = _REGISTRY.get(name)
        if existing is None:
            existing = CircuitBreaker(
                name,
                failure_threshold=failure_threshold,
                reset_timeout_seconds=reset_timeout_seconds,
            )
            _REGISTRY[name] = existing
        return existing


def snapshots() -> list[BreakerSnapshot]:
    with _REGISTRY_LOCK:
        breakers = list(_REGISTRY.values())
    return sorted((one.snapshot() for one in breakers), key=lambda row: row.name)


def reset_all() -> None:
    with _REGISTRY_LOCK:
        breakers = list(_REGISTRY.values())
    for one in breakers:
        one.reset()
