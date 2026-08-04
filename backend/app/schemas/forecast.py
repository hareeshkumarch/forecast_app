from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.models.enums import (
    ForecastFrequency,
    GapFill,
    MeasureAggregation,
    ModelKind,
    OutlierTreatment,
    PointKind,
    RunStatus,
)
from app.schemas.common import (
    Identifier,
    NonNegativeFloat,
    NonNegativeInt,
    ORMModel,
    Percentage,
    Probability,
    StrictModel,
)

SCORABLE_METRICS = frozenset({"wmape", "smape", "rmse", "mae"})

Horizon = Annotated[int, Field(ge=1, le=365)]
Folds = Annotated[int, Field(ge=1, le=10)]
TreeDepth = Annotated[int, Field(ge=1, le=10)]
ArimaOrder = Annotated[list[Annotated[int, Field(ge=0, le=5)]], Field(min_length=3, max_length=3)]


class ForecastRunRequest(StrictModel):
    dataset_id: uuid.UUID
    name: Identifier | None = None
    time_column: Identifier | None = None
    target_column: Identifier | None = None
    weight_column: Identifier | None = None
    region_column: Identifier | None = None
    category_column: Identifier | None = None
    frequency: ForecastFrequency | None = None
    horizon: Horizon | None = None
    confidence_level: Probability = 0.8
    aggregation: MeasureAggregation = MeasureAggregation.SUM
    gap_fill: GapFill = GapFill.AUTO
    outlier_treatment: OutlierTreatment = OutlierTreatment.NONE
    max_folds: Folds | None = None
    metric_weights: dict[str, float] | None = None
    sarimax_order: ArimaOrder | None = None
    gbm_max_depth: TreeDepth | None = None
    llm_provider: Identifier | None = None
    llm_api_key: str | None = Field(default=None, max_length=512, repr=False)
    llm_model: Identifier | None = None
    llm_base_url: str | None = Field(default=None, max_length=512)

    @field_validator("metric_weights")
    @classmethod
    def _weights_are_scorable(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value is None:
            return None

        unknown = sorted(set(value) - SCORABLE_METRICS)
        if unknown:
            raise ValueError(
                f"Unknown metric(s) {', '.join(unknown)}; choose from {', '.join(sorted(SCORABLE_METRICS))}."
            )
        if any(weight < 0 for weight in value.values()):
            raise ValueError("Metric weights cannot be negative.")
        if sum(value.values()) <= 0:
            raise ValueError("Metric weights must sum to more than zero.")
        return value

    @model_validator(mode="after")
    def _columns_are_distinct(self) -> Self:
        assigned = [
            (role, column)
            for role, column in (
                ("time", self.time_column),
                ("target", self.target_column),
                ("weight", self.weight_column),
                ("region", self.region_column),
                ("category", self.category_column),
            )
            if column
        ]

        seen: dict[str, str] = {}
        for role, column in assigned:
            if column in seen:
                raise ValueError(
                    f"'{column}' cannot be both the {seen[column]} and the {role} column."
                )
            seen[column] = role
        return self


class ModelCandidateRead(ORMModel):
    id: uuid.UUID
    model: ModelKind
    rank: NonNegativeInt
    selected: bool
    mae: float | None
    rmse: float | None
    smape: float | None
    wmape: float | None
    score: float | None
    folds: NonNegativeInt
    fit_seconds: NonNegativeFloat | None
    params: dict[str, object]
    failed: bool
    failure_reason: str | None


class ForecastMetricRead(ORMModel):
    name: Identifier
    value: float
    unit: Identifier
    previous_value: float | None

    @computed_field
    @property
    def delta(self) -> float | None:
        if self.previous_value is None:
            return None
        return round(self.value - self.previous_value, 6)


class ForecastPointRead(ORMModel):
    period: date
    kind: PointKind
    actual: float | None
    forecast: float | None
    lower_bound: float | None
    upper_bound: float | None
    best_case: float | None
    base_case: float | None
    worst_case: float | None


class ForecastRunRead(ORMModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    status: RunStatus
    progress: Annotated[float, Field(ge=0.0, le=1.0)]
    stage: str
    time_column: str
    target_column: str
    weight_column: str | None
    region_column: str | None
    category_column: str | None
    frequency: ForecastFrequency
    horizon: Horizon
    confidence_level: Probability
    aggregation: MeasureAggregation
    gap_fill: GapFill
    outlier_treatment: OutlierTreatment
    selected_model: ModelKind | None
    selection_rationale: str | None
    used_fallback: bool
    fallback_reason: str | None
    history_start: date | None
    history_end: date | None
    forecast_start: date | None
    forecast_end: date | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime

    @computed_field
    @property
    def is_terminal(self) -> bool:
        return self.status in (RunStatus.COMPLETED, RunStatus.FAILED)


class ForecastRunDetail(ForecastRunRead):
    candidates: list[ModelCandidateRead] = Field(default_factory=list)
    metrics: list[ForecastMetricRead] = Field(default_factory=list)


class ForecastMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    selected_model: ModelKind | None
    selection_rationale: str | None
    scoring_rule: str
    metrics: list[ForecastMetricRead]
    candidates: list[ModelCandidateRead]

    @computed_field
    @property
    def scored_candidates(self) -> int:
        return sum(1 for candidate in self.candidates if not candidate.failed)


class ForecastPointsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    frequency: ForecastFrequency
    confidence_level: Probability
    boundary_index: NonNegativeInt | None
    points: list[ForecastPointRead]

    @computed_field
    @property
    def horizon(self) -> int:
        if self.boundary_index is None:
            return 0
        return max(len(self.points) - self.boundary_index, 0)


class ForecastProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    status: RunStatus
    progress: Annotated[float, Field(ge=0.0, le=1.0)]
    stage: str
    message: str | None = None
    selected_model: ModelKind | None = None
    error: str | None = None

    @computed_field
    @property
    def percent(self) -> Percentage:
        return round(self.progress * 100.0, 2)
