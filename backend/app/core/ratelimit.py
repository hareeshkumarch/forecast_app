"""Sliding-window rate limiting, in this process, without a Redis to run.

A sliding window log rather than a fixed counter: a fixed window lets somebody
spend a whole allowance in the last second of one window and the whole of the
next in the first second of the next, which is twice the limit in a moment and
exactly the burst the limit exists to stop.

Kept in memory deliberately. This deployment runs one uvicorn process on a 2 GB
instance where the production compose drops redis so the forecast pool gets the
RAM. Across one process an in-memory log is exactly as correct as a shared
store and costs nothing. Across two it is not: each instance would enforce its
own copy of every limit, so the real ceiling doubles. That is the day to move
this behind a shared store, and `SPLITS_ACROSS_PROCESSES` is here to be found
by the person looking for why the numbers stopped adding up.

Identity is the client IP. Not the account: the middleware runs before any
route dependency, so nothing here has verified a token, and keying on an
unverified claim would let anybody mint themselves a fresh allowance by
changing one character of it. An IP cannot be chosen quite so freely.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from dataclasses import dataclass

SPLITS_ACROSS_PROCESSES = True

#: Beyond this many tracked clients the least recently seen are dropped. An
#: unbounded map keyed by remote address is a memory leak with a public
#: trigger. Dropping the oldest forgets somebody who has not been seen for a
#: while, which costs them nothing — their window had almost certainly expired.
MAX_TRACKED = 20_000


@dataclass(frozen=True, slots=True)
class Rule:
    limit: int
    window_seconds: float
    name: str

    def retry_after(self, oldest: float, now: float) -> int:
        return max(1, int(oldest + self.window_seconds - now) + 1)


#: The emailed approve/reject link is the one endpoint where guessing pays: a
#: valid signature is a decision on somebody's account, made without a session.
#: The signature is 32 bytes of HMAC and will not fall to a brute force either
#: way, but there is no reason to let anybody try at speed.
DECIDE = Rule(limit=10, window_seconds=900, name="decide")

#: Administrative changes. Generous enough for somebody working through a list
#: of twenty people, tight enough that a stolen session cannot enumerate.
ADMIN = Rule(limit=60, window_seconds=60, name="admin")

#: A forecast run is a minute of two vCPUs. This is the limit that protects the
#: box rather than the data.
RUN = Rule(limit=20, window_seconds=3600, name="run")

#: Uploads are parsed, profiled and written to disk.
UPLOAD = Rule(limit=40, window_seconds=3600, name="upload")

#: Everything else. A page of this app fires a dozen queries on load, and a
#: person clicking around fires them repeatedly, so this has to sit well above
#: anything a human generates.
DEFAULT = Rule(limit=240, window_seconds=60, name="default")

#: Health is what a load balancer and a deploy script call, sometimes in a
#: tight loop, and a rate-limited health check reads as an outage. The event
#: streams are long-lived by design and are limited by the connection count
#: rather than by a request rate.
EXEMPT_PREFIXES = ("/api/health", "/docs", "/redoc", "/openapi.json")
EXEMPT_SUFFIXES = ("/events",)


def rule_for(method: str, path: str) -> Rule | None:
    if path.startswith(EXEMPT_PREFIXES) or path.endswith(EXEMPT_SUFFIXES):
        return None
    if path.startswith("/api/auth/decide"):
        return DECIDE
    if method != "GET" and path.startswith("/api/auth/"):
        return ADMIN
    if method == "POST" and path.startswith("/api/forecasts"):
        return RUN
    if method == "POST" and path.startswith("/api/datasets"):
        return UPLOAD
    return DEFAULT


class SlidingWindow:
    def __init__(self, max_tracked: int = MAX_TRACKED) -> None:
        self._seen: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._max_tracked = max_tracked

    def check(self, identity: str, rule: Rule, now: float | None = None) -> tuple[bool, int, int]:
        """Record an attempt. Returns (allowed, remaining, reset_seconds).

        The attempt is recorded only when it is allowed. Counting refusals
        would mean a client that keeps hammering never comes off the limit,
        which turns a momentary burst into an indefinite block.
        """
        now = time.monotonic() if now is None else now
        key = (identity, rule.name)

        window = self._seen.get(key)
        if window is None:
            window = deque()
            self._seen[key] = window
        self._seen.move_to_end(key)

        cutoff = now - rule.window_seconds
        while window and window[0] <= cutoff:
            window.popleft()

        if len(window) >= rule.limit:
            return False, 0, rule.retry_after(window[0], now)

        window.append(now)
        self._prune()
        reset = int(window[0] + rule.window_seconds - now) + 1 if window else int(
            rule.window_seconds
        )
        return True, rule.limit - len(window), max(1, reset)

    def _prune(self) -> None:
        while len(self._seen) > self._max_tracked:
            self._seen.popitem(last=False)

    def forget_all(self) -> None:
        self._seen.clear()

    @property
    def tracked(self) -> int:
        return len(self._seen)


limiter = SlidingWindow()


def client_identity(headers, client_host: str | None) -> str:
    """Who to count this against.

    X-Forwarded-For is written by whatever proxied the request, and the
    leftmost entry is the client as that proxy saw it. It is also trivially
    forged by anybody who can reach this box directly — which today is anybody,
    because the instance still answers the open internet on port 80. Until that
    origin is closed, treat this as a control against accident and ordinary
    abuse rather than against somebody determined, and do not let it be the
    only thing standing anywhere.
    """
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return headers.get("x-real-ip", "").strip() or client_host or "unknown"
