from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import ForecastFrequency, ModelKind, PointKind, RunStatus
from app.schemas.common import ORMModel


class ForecastRunRequest(BaseModel):
    dataset_id: uuid.UUID
    name: str | None = None
    time_column: str | None = None
    target_column: str | None = None
    weight_column: str | None = None
    region_column: str | None = None
    category_column: str | None = None
    frequency: ForecastFrequency | None = None
    horizon: int | None = Field(default=None, ge=1, le=365)
    confidence_level: float = Field(default=0.8, gt=0.5, lt=1.0)
    max_folds: int | None = Field(default=None, ge=1, le=10)
    metric_weights: dict[str, float] | None = None
    sarimax_order: list[int] | None = None
    gbm_max_depth: int | None = Field(default=None, ge=1, le=10)
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None


class ModelCandidateRead(ORMModel):
    id: uuid.UUID
    model: ModelKind
    rank: int
    selected: bool
    mae: float | None
    rmse: float | None
    smape: float | None
    wmape: float | None
    score: float | None
    folds: int
    fit_seconds: float | None
    params: dict
    failed: bool
    failure_reason: str | None


class ForecastMetricRead(ORMModel):
    name: str
    value: float
    unit: str
    previous_value: float | None


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
    progress: float
    stage: str
    time_column: str
    target_column: str
    weight_column: str | None
    region_column: str | None
    category_column: str | None
    frequency: ForecastFrequency
    horizon: int
    confidence_level: float
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


class ForecastRunDetail(ForecastRunRead):
    candidates: list[ModelCandidateRead] = Field(default_factory=list)
    metrics: list[ForecastMetricRead] = Field(default_factory=list)


class ForecastMetricsResponse(BaseModel):
    run_id: uuid.UUID
    selected_model: ModelKind | None
    selection_rationale: str | None
    scoring_rule: str
    metrics: list[ForecastMetricRead]
    candidates: list[ModelCandidateRead]


class ForecastPointsResponse(BaseModel):
    run_id: uuid.UUID
    frequency: ForecastFrequency
    confidence_level: float


    boundary_index: int | None
    points: list[ForecastPointRead]


class ForecastProgressEvent(BaseModel):

    run_id: uuid.UUID
    status: RunStatus
    progress: float
    stage: str
    message: str | None = None
    selected_model: ModelKind | None = None
    error: str | None = None
