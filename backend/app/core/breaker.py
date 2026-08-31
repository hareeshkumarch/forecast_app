"""A circuit breaker, so a dependency having a bad minute costs one timeout.

The platform's insight rewrite fans eight concurrent calls out to whichever
model provider is configured. When that provider is healthy the fan is the
point. When it is timing out, the fan is eight ten-second waits, and the next
person who presses the button pays for eight more — the failure costs more the
worse it gets, which is the shape of an outage that spreads.

A breaker turns that into: fail a few times, then stop calling for half a
minute, then let exactly one call through to find out whether it is over.

**What counts as a failure is the interesting decision.** Not "the call did
not produce a usable answer". A `401` is a wrong key, a `404` is a wrong model
name, and a model that answered with a figure it invented is a model behaving
badly — all three arrive promptly, cost nothing, and are fixed by a person
changing a setting. Tripping on them would mean somebody who has just pasted a
corrected key waits thirty seconds to find out it works, which is a breaker
making the product worse. Only *transport* failures count: timeouts, refused
connections, 5xx and 429. Those are the ones where calling again immediately
is both expensive and pointless. `is_transport_failure` is that rule, in one
place, testable.

**Half-open admits one caller, not all of them.** The naive version lets the
whole backlog through the moment the cooldown expires, which re-floors a
service that is still on its knees. One trial call decides for everybody.

**Synchronous, and that is not an oversight.** The call site that needs this
is `httpx.Client` on a worker thread, not the async client, so a breaker that
only wrapped coroutines would not fit the one place it is for. The state is
guarded by a plain `threading.Lock` for the same reason — it is read and
written from the rewrite pool's threads as well as from the event loop. An
async wrapper is a handful of lines the day something needs one.
"""

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


#: What the state gauge reads. Ordered so that "worse" is a larger number and
#: an alert can be written as `> 0` without enumerating the names.
_STATE_VALUE = {BreakerState.CLOSED: 0.0, BreakerState.HALF_OPEN: 1.0, BreakerState.OPEN: 2.0}

#: Status codes that mean "this service is struggling", as opposed to "your
#: request was wrong". 408 and 425 are the server saying it gave up waiting;
#: 429 is it asking for less; 5xx is it failing. Everything else in the 4xx
#: range is about the request and is not the dependency's health.
_TRANSPORT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504, 507, 509, 522, 524})


class CircuitOpenError(AppError):
    """Raised by `call`/`guard` while the breaker is open.

    503 rather than 500: nothing went wrong processing this request, a
    dependency is unavailable, and the client should try later. `Retry-After`
    is carried in the detail so a caller that wants to surface a wait can.
    """

    status_code = 503
    code = "upstream_unavailable"


def is_transport_failure(exc: BaseException) -> bool:
    """Whether this exception says the dependency is unhealthy.

    Deliberately narrow, and deliberately not "any exception". See the module
    docstring: a wrong key is not an outage, and treating it as one makes the
    fix take longer than the mistake.
    """
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
        #: When the one half-open trial went out, or None when none is. While
        #: a trial is out everybody else is refused, so a cooled-down breaker
        #: does not release the whole backlog at a service still unwell.
        #:
        #: A timestamp rather than a flag, because the flag has a liveness bug
        #: hiding in it: a caller that claims the trial and then never reports
        #: back — a thread that died, a code path that returned early — leaves
        #: the breaker refusing everything forever, with no failure anywhere
        #: to explain why. The claim therefore expires on the same cooldown
        #: that granted it. The worst that costs is a second trial call; the
        #: alternative costs the dependency.
        self._trial_started_at: float | None = None
        metrics.breaker_state.set(_STATE_VALUE[BreakerState.CLOSED], breaker=name)

    # ---- state ------------------------------------------------------------

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
        """Move OPEN to HALF_OPEN once the cooldown has passed. Caller holds the lock."""
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

    # ---- admission --------------------------------------------------------

    def allows(self) -> bool:
        """Whether a call may go out now, claiming the half-open trial if so.

        A caller told yes owes the breaker an outcome: `record_success`,
        `record_failure`, or `release_trial` if it decided not to call after
        all. `call` does this for you, and is the version to reach for unless
        the call site has to shape its own result.
        """
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
        """Whether the one half-open trial is genuinely still out.

        Caller holds the lock. A claim older than the cooldown is treated as
        abandoned — see `_trial_started_at`.
        """
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
        """Hand back a claimed trial without reporting an outcome.

        For the caller that asked `allows()`, was told yes, and then did not
        make the call after all. Every other path must use `record_success` or
        `record_failure`: those carry evidence, and this one carries none.
        """
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
                # A failed trial re-opens immediately whatever the count: the
                # one call allowed through is the whole evidence, and making
                # it earn the full threshold again would send three more
                # requests into something already known to be down.
                self._opened_at = now
                self._set(BreakerState.OPEN)

    def reset(self) -> None:
        """Back to closed and forgetful. For tests and for an explicit retry."""
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._trial_started_at = None
            self._set(BreakerState.CLOSED)

    # ---- calling ----------------------------------------------------------

    def call(self, fn: Callable[[], T]) -> T:
        """Run `fn` behind the breaker, raising `CircuitOpenError` when open."""
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
                # An answer, even an unwelcome one, is evidence the dependency
                # is up. Recording it as a success is what keeps a wrong API
                # key from being mistaken for an outage.
                self.record_success()
            raise
        else:
            self.record_success()
            return result


#: Breakers by name, so `/api/health` can report every one without a list that
#: somebody has to remember to add to.
_REGISTRY: dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK = threading.Lock()


def breaker(
    name: str, *, failure_threshold: int = 4, reset_timeout_seconds: float = 30.0
) -> CircuitBreaker:
    """The breaker with this name, creating it on first ask.

    Shared by name, which is the whole point: every caller aimed at one
    dependency has to be looking at one piece of state, or the fourth failure
    never meets the third. The consequence to know is that the keyword
    arguments configure it **only on the call that creates it** — a later call
    with a different threshold gets the existing breaker, unchanged, rather
    than silently reconfiguring one that other callers are relying on. Read a
    breaker's `failure_threshold` if you need to know what it actually is.
    """
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
