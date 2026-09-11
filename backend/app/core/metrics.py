from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

MAX_SERIES: Final = 512

_NAME_PATTERN: Final = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_LOCK = threading.Lock()

LabelValues = tuple[tuple[str, str], ...]

LATENCY_BUCKETS: Final[tuple[float, ...]] = (
    0.005,
    0.010,
    0.025,
    0.050,
    0.100,
    0.250,
    0.500,
    1.0,
    2.5,
    5.0,
    10.0,
)


def _escape(value: str) -> str:
    return value.replace("\\", r"\\").replace("\n", r"\n").replace('"', r"\"")


def _render_number(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


@dataclass(slots=True)
class _Metric:
    name: str
    help_text: str
    labels: tuple[str, ...] = ()
    _overflowed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not _NAME_PATTERN.match(self.name):
            raise ValueError(f"{self.name!r} is not a valid metric name.")
        for label in self.labels:
            if not _NAME_PATTERN.match(label):
                raise ValueError(f"{label!r} is not a valid label name.")

    def _key(self, values: Mapping[str, str], existing: int) -> LabelValues:
        key = tuple((name, str(values.get(name, ""))) for name in self.labels)
        if existing >= MAX_SERIES and key not in self._known():
            self._overflowed = True
            return tuple((name, "overflow") for name in self.labels)
        return key

    def _known(self) -> Iterable[LabelValues]:  # pragma: no cover - overridden
        return ()

    @property
    def overflowed(self) -> bool:
        return self._overflowed


class Counter(_Metric):
    def __init__(self, name: str, help_text: str, labels: Sequence[str] = ()) -> None:
        super().__init__(name, help_text, tuple(labels))
        self._values: dict[LabelValues, float] = {}

    def _known(self) -> Iterable[LabelValues]:
        return self._values.keys()

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            raise ValueError("A counter cannot be decremented.")
        with _LOCK:
            key = self._key(labels, len(self._values))
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **labels: str) -> float:
        with _LOCK:
            return self._values.get(
                tuple((name, str(labels.get(name, ""))) for name in self.labels), 0.0
            )

    def samples(self) -> list[tuple[str, LabelValues, float]]:
        with _LOCK:
            return [(self.name, key, value) for key, value in sorted(self._values.items())]

    def reset(self) -> None:
        with _LOCK:
            self._values.clear()
            self._overflowed = False


class Gauge(_Metric):
    def __init__(self, name: str, help_text: str, labels: Sequence[str] = ()) -> None:
        super().__init__(name, help_text, tuple(labels))
        self._values: dict[LabelValues, float] = {}

    def _known(self) -> Iterable[LabelValues]:
        return self._values.keys()

    def set(self, value: float, **labels: str) -> None:
        with _LOCK:
            self._values[self._key(labels, len(self._values))] = float(value)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        with _LOCK:
            key = self._key(labels, len(self._values))
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        self.inc(-amount, **labels)

    def value(self, **labels: str) -> float:
        with _LOCK:
            return self._values.get(
                tuple((name, str(labels.get(name, ""))) for name in self.labels), 0.0
            )

    def samples(self) -> list[tuple[str, LabelValues, float]]:
        with _LOCK:
            return [(self.name, key, value) for key, value in sorted(self._values.items())]

    def reset(self) -> None:
        with _LOCK:
            self._values.clear()
            self._overflowed = False


@dataclass(slots=True)
class _Bucketed:
    counts: list[float]
    total: float = 0.0
    count: float = 0.0


class Histogram(_Metric):
    def __init__(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str] = (),
        buckets: Sequence[float] = LATENCY_BUCKETS,
    ) -> None:
        super().__init__(name, help_text, tuple(labels))
        ordered = tuple(sorted(float(bound) for bound in buckets))
        if not ordered:
            raise ValueError("A histogram needs at least one bucket.")
        if len(set(ordered)) != len(ordered):
            raise ValueError("Histogram bucket bounds must be distinct.")
        self.buckets: tuple[float, ...] = (*ordered, math.inf)
        self._values: dict[LabelValues, _Bucketed] = {}

    def _known(self) -> Iterable[LabelValues]:
        return self._values.keys()

    def observe(self, value: float, **labels: str) -> None:
        if math.isnan(value):
            return
        with _LOCK:
            key = self._key(labels, len(self._values))
            row = self._values.get(key)
            if row is None:
                row = _Bucketed(counts=[0.0] * len(self.buckets))
                self._values[key] = row
            row.total += value
            row.count += 1.0
            for index, bound in enumerate(self.buckets):
                if value <= bound:
                    row.counts[index] += 1.0

    def count_of(self, **labels: str) -> float:
        with _LOCK:
            row = self._values.get(tuple((name, str(labels.get(name, ""))) for name in self.labels))
            return row.count if row else 0.0

    def sum_of(self, **labels: str) -> float:
        with _LOCK:
            row = self._values.get(tuple((name, str(labels.get(name, ""))) for name in self.labels))
            return row.total if row else 0.0

    def samples(self) -> list[tuple[str, LabelValues, float]]:
        with _LOCK:
            rows = sorted(self._values.items())
        out: list[tuple[str, LabelValues, float]] = []
        for key, row in rows:
            for bound, count in zip(self.buckets, row.counts, strict=True):
                out.append((f"{self.name}_bucket", (*key, ("le", _render_number(bound))), count))
            out.append((f"{self.name}_sum", key, row.total))
            out.append((f"{self.name}_count", key, row.count))
        return out

    def reset(self) -> None:
        with _LOCK:
            self._values.clear()
            self._overflowed = False


class Registry:
    def __init__(self) -> None:
        self._metrics: dict[str, _Metric] = {}

    def register(self, metric: _Metric) -> _Metric:
        existing = self._metrics.get(metric.name)
        if existing is not None:
            return existing
        self._metrics[metric.name] = metric
        return metric

    def counter(self, name: str, help_text: str, labels: Sequence[str] = ()) -> Counter:
        metric = self.register(Counter(name, help_text, labels))
        assert isinstance(metric, Counter)
        return metric

    def gauge(self, name: str, help_text: str, labels: Sequence[str] = ()) -> Gauge:
        metric = self.register(Gauge(name, help_text, labels))
        assert isinstance(metric, Gauge)
        return metric

    def histogram(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str] = (),
        buckets: Sequence[float] = LATENCY_BUCKETS,
    ) -> Histogram:
        metric = self.register(Histogram(name, help_text, labels, buckets))
        assert isinstance(metric, Histogram)
        return metric

    def reset(self) -> None:
        for metric in self._metrics.values():
            metric.reset()  # type: ignore[attr-defined]

    def render(self) -> str:
        lines: list[str] = []
        for name in sorted(self._metrics):
            metric = self._metrics[name]
            kind = (
                "counter"
                if isinstance(metric, Counter)
                else "gauge"
                if isinstance(metric, Gauge)
                else "histogram"
            )
            lines.append(f"# HELP {name} {metric.help_text}")
            lines.append(f"# TYPE {name} {kind}")
            for sample_name, key, value in metric.samples():  # type: ignore[attr-defined]
                lines.append(f"{sample_name}{_labels(key)} {_render_number(value)}")
        return "\n".join(lines) + "\n"


def _labels(key: LabelValues) -> str:
    if not key:
        return ""
    inner = ",".join(f'{name}="{_escape(value)}"' for name, value in key)
    return "{" + inner + "}"


registry = Registry()


http_requests = registry.counter(
    "forecasting_http_requests_total",
    "HTTP requests served, by route template, method and status class.",
    ("route", "method", "status"),
)

http_request_seconds = registry.histogram(
    "forecasting_http_request_duration_seconds",
    "Wall time from the first middleware to the response, by route template.",
    ("route", "method"),
)

http_in_flight = registry.gauge(
    "forecasting_http_requests_in_flight",
    "Requests currently being served by this process.",
)

http_shed = registry.counter(
    "forecasting_http_requests_shed_total",
    "Requests refused with 503 because this process was already at its concurrency ceiling.",
    ("route",),
)

rate_limited = registry.counter(
    "forecasting_rate_limited_total",
    "Requests refused with 429, by the rule that refused them.",
    ("rule",),
)

cache_events = registry.counter(
    "forecasting_cache_events_total",
    "Read-through cache outcomes, by cache name and outcome (hit, miss, coalesced, evicted).",
    ("cache", "outcome"),
)

cache_entries = registry.gauge(
    "forecasting_cache_entries",
    "Entries currently held, by cache name.",
    ("cache",),
)

conditional_responses = registry.counter(
    "forecasting_conditional_responses_total",
    "Answers to a conditional GET, by outcome (not_modified, rendered).",
    ("route", "outcome"),
)

breaker_state = registry.gauge(
    "forecasting_circuit_breaker_state",
    "Circuit breaker state by name: 0 closed, 1 half-open, 2 open.",
    ("breaker",),
)

breaker_events = registry.counter(
    "forecasting_circuit_breaker_events_total",
    "Circuit breaker transitions and refusals, by name and event.",
    ("breaker", "event"),
)

forecast_runs = registry.counter(
    "forecasting_runs_total",
    "Forecast runs that reached a terminal state, by that state.",
    ("status",),
)

stored_bytes = registry.gauge(
    "forecasting_table_bytes",
    "Bytes on disk per table, indexes and TOAST included. Refreshed on scrape.",
    ("table",),
)

stored_rows = registry.gauge(
    "forecasting_table_rows",
    "Rows per table, as the planner estimates them. Refreshed on scrape.",
    ("table",),
)

retention_removed = registry.counter(
    "forecasting_retention_removed_total",
    "Forecast runs removed by the retention sweeper.",
)

forecast_run_seconds = registry.histogram(
    "forecasting_run_duration_seconds",
    "Wall time of a forecast run from dispatch to terminal state.",
    (),
    buckets=(5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1200.0, 1800.0),
)


class Timer:
    __slots__ = ("_histogram", "_labels", "_started")

    def __init__(self, histogram: Histogram, **labels: str) -> None:
        self._histogram = histogram
        self._labels = labels
        self._started = 0.0

    def __enter__(self) -> Timer:
        self._started = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self._histogram.observe(time.perf_counter() - self._started, **self._labels)

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._started
