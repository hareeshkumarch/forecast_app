from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address

from app.core.config import settings

SPLITS_ACROSS_PROCESSES = True

MAX_TRACKED = 20_000


@dataclass(frozen=True, slots=True)
class Rule:
    limit: int
    window_seconds: float
    name: str

    def retry_after(self, oldest: float, now: float) -> int:
        return max(1, int(oldest + self.window_seconds - now) + 1)


DECIDE = Rule(limit=10, window_seconds=900, name="decide")

ADMIN = Rule(limit=60, window_seconds=60, name="admin")

RUN = Rule(limit=20, window_seconds=3600, name="run")

UPLOAD = Rule(limit=40, window_seconds=3600, name="upload")

DEFAULT = Rule(limit=240, window_seconds=60, name="default")

EXEMPT_PREFIXES = ("/api/health", "/docs", "/redoc", "/openapi.json")
EXEMPT_SUFFIXES = ("/events",)


def rule_for(method: str, path: str) -> Rule | None:
    if path.startswith(EXEMPT_PREFIXES) or path.endswith(EXEMPT_SUFFIXES):
        return None
    if path.startswith("/api/auth/decide"):
        return DECIDE
    if method != "GET" and path.startswith("/api/auth/"):
        return ADMIN
    if path.startswith("/api/forecasts/retention"):
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
        reset = (
            int(window[0] + rule.window_seconds - now) + 1 if window else int(rule.window_seconds)
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


def _trusted_peer(client_host: str | None) -> bool:
    networks = settings.rate_limit_trusted_proxies
    if not networks:
        return True
    if not client_host:
        return False
    try:
        peer = ip_address(client_host)
    except ValueError:
        return False
    return any(peer in network for network in networks)


def client_identity(headers: Mapping[str, str], client_host: str | None) -> str:
    if not _trusted_peer(client_host):
        return client_host or "unknown"

    hops = max(1, settings.rate_limit_trusted_proxy_hops)
    chain = [part.strip() for part in headers.get("x-forwarded-for", "").split(",")]
    chain = [part for part in chain if part]
    if chain:
        return chain[-hops] if len(chain) >= hops else chain[0]
    return headers.get("x-real-ip", "").strip() or client_host or "unknown"
