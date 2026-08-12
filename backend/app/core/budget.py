from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum


class Stage(StrEnum):
    PARSE = "parse"
    VALIDATE = "validate"
    CLASSIFY = "classify"
    FEATURES = "features"
    FIT = "fit"
    PREDICT = "predict"
    CALIBRATE = "calibrate"
    PERSIST = "persist"


TOTAL_BUDGET_SECONDS = 60.0

STAGE_BUDGET_SECONDS: dict[Stage, float] = {
    Stage.PARSE: 6.0,
    Stage.VALIDATE: 3.0,
    Stage.CLASSIFY: 2.0,
    Stage.FEATURES: 4.0,
    Stage.FIT: 28.0,
    Stage.PREDICT: 4.0,
    Stage.CALIBRATE: 3.0,
    Stage.PERSIST: 4.0,
}

SERIES_CEILING = 500

SERIES_HARD_LIMIT = 20_000


@dataclass(slots=True)
class StageTiming:
    stage: Stage
    seconds: float

    @property
    def budget(self) -> float:
        return STAGE_BUDGET_SECONDS[self.stage]

    @property
    def over(self) -> bool:
        return self.seconds > self.budget

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "seconds": round(self.seconds, 4),
            "budget": self.budget,
            "over": self.over,
        }


@dataclass(slots=True)
class RunTimings:

    stages: list[StageTiming] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(timing.seconds for timing in self.stages)

    @property
    def within_budget(self) -> bool:
        return self.total <= TOTAL_BUDGET_SECONDS

    @property
    def overruns(self) -> list[StageTiming]:
        return [timing for timing in self.stages if timing.over]

    def seconds_in(self, stage: Stage) -> float:
        return sum(t.seconds for t in self.stages if t.stage is stage)

    def record(self, stage: Stage, seconds: float) -> None:
        self.stages.append(StageTiming(stage=stage, seconds=seconds))

    @contextmanager
    def measure(self, stage: Stage) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record(stage, time.perf_counter() - started)

    def as_dict(self) -> dict[str, object]:
        return {
            "total_seconds": round(self.total, 4),
            "budget_seconds": TOTAL_BUDGET_SECONDS,
            "within_budget": self.within_budget,
            "stages": [timing.as_dict() for timing in self.stages],
            "overruns": [timing.stage.value for timing in self.overruns],
        }


class Admission(StrEnum):
    INLINE = "inline"
    QUEUE = "queue"
    REFUSE = "refuse"


@dataclass(slots=True, frozen=True)
class AdmissionDecision:
    admission: Admission
    series_count: int
    message: str

    @property
    def accepted(self) -> bool:
        return self.admission is not Admission.REFUSE

    def as_dict(self) -> dict[str, object]:
        return {
            "admission": self.admission.value,
            "series_count": self.series_count,
            "ceiling": SERIES_CEILING,
            "hard_limit": SERIES_HARD_LIMIT,
            "message": self.message,
        }


def admission(series_count: int) -> AdmissionDecision:
    if series_count > SERIES_HARD_LIMIT:
        return AdmissionDecision(
            admission=Admission.REFUSE,
            series_count=series_count,
            message=(
                f"This file splits into {series_count:,} series, past the {SERIES_HARD_LIMIT:,} "
                "this can forecast. That is usually a grain that includes an order or "
                "transaction reference — group by product, region or channel instead."
            ),
        )
    if series_count > SERIES_CEILING:
        return AdmissionDecision(
            admission=Admission.QUEUE,
            series_count=series_count,
            message=(
                f"{series_count:,} series is past the {SERIES_CEILING:,} that finish in about a "
                "minute, so this run is queued and reports progress as it goes."
            ),
        )
    return AdmissionDecision(
        admission=Admission.INLINE,
        series_count=series_count,
        message=f"{series_count:,} series, which finishes in about a minute.",
    )


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * len(ordered) + 0.5)) - 1))
    return ordered[index]
