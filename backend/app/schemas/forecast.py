from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator
from typing_extensions import Self  # noqa: UP035

from app.datasets.queries import DEFAULT_MAX_SERIES
from app.models.enums import (
    ForecastFrequency,
    GapFill,
    MeasureAggregation,
    ModelKind,
    OutlierTreatment,
    PointKind,
    RunStatus,
    SeriesStatus,
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

#: What a caller may weigh model selection by. sMAPE is deliberately absent:
#: it is undefined wherever an actual and its forecast are both zero, so on
#: intermittent demand it scores only the weeks that had sales and ranks
#: candidates on that slice. It is still reported; it just cannot decide.
SCORABLE_METRICS = frozenset({"wmape", "mase", "rmse", "mae"})


def _accuracy(wmape: float | None) -> float | None:
    from app.forecasting.metrics import accuracy_from_wmape

    if wmape is None:
        return None
    value = accuracy_from_wmape(wmape)
    return None if value != value else round(value, 2)


Horizon = Annotated[int, Field(ge=1, le=365)]
Folds = Annotated[int, Field(ge=1, le=10)]
TreeDepth = Annotated[int, Field(ge=1, le=10)]
LearningRate = Annotated[float, Field(gt=0.0, le=1.0)]
SeriesLimit = Annotated[int, Field(ge=1, le=DEFAULT_MAX_SERIES)]
ArimaOrder = Annotated[list[Annotated[int, Field(ge=0, le=5)]], Field(min_length=3, max_length=3)]


class ForecastRunRequest(StrictModel):
    dataset_id: uuid.UUID
    name: Identifier | None = None
    time_column: Identifier | None = None
    target_column: Identifier | None = None
    weight_column: Identifier | None = None
    region_column: Identifier | None = None
    category_column: Identifier | None = None
    group_by: Annotated[list[Identifier], Field(max_length=4)] = Field(default_factory=list)
    frequency: ForecastFrequency | None = None
    horizon: Horizon | None = None
    confidence_level: Probability = 0.8
    #: Left unset, the run picks the reducer that suits the target — summing a
    #: price or a conversion rate gives a number that grows with the row count.
    #: Set explicitly, what was asked for is what runs.
    aggregation: MeasureAggregation | None = None
    gap_fill: GapFill = GapFill.AUTO
    outlier_treatment: OutlierTreatment = OutlierTreatment.NONE
    max_folds: Folds | None = None
    max_series: SeriesLimit | None = None
    metric_weights: dict[str, float] | None = None
    sarimax_order: ArimaOrder | None = None
    gbm_max_depth: TreeDepth | None = None
    gbm_learning_rate: LearningRate | None = None
    candidate_models: list[ModelKind] | None = None
    prophet_changepoint_prior_scale: float | None = Field(default=None, ge=0.001, le=1.0)
    prophet_interval_width: float | None = Field(default=None, ge=0.5, le=0.99)
    outlier_mad_threshold: float | None = Field(default=None, ge=1.0, le=20.0)
    complexity_penalty_scale: float | None = Field(default=None, ge=0.0, le=10.0)
    driver_columns: list[Identifier] | None = None
    llm_provider: Identifier | None = None
    llm_api_key: str | None = Field(default=None, max_length=512, repr=False)
    llm_model: Identifier | None = None
    llm_base_url: str | None = Field(default=None, max_length=512)
    llm_input_cost_per_million: float | None = Field(default=None, ge=0.0, le=100_000.0)
    llm_output_cost_per_million: float | None = Field(default=None, ge=0.0, le=100_000.0)

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

    @field_validator("group_by")
    @classmethod
    def _grain_has_no_repeats(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("The forecast grain lists the same column twice.")
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


class LeadingColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    lag: NonNegativeInt
    direction: str = "up"


class ModelCandidateRead(ORMModel):
    id: uuid.UUID
    model: ModelKind
    rank: NonNegativeInt
    selected: bool
    mae: float | None
    rmse: float | None
    smape: float | None
    wmape: float | None
    mase: float | None = None
    winkler: float | None = None
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


class SeriesRow(ORMModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    level: NonNegativeInt
    key: dict[str, str]
    label: str
    status: SeriesStatus
    blocked_reason: str | None
    model: ModelKind | None
    wmape: float | None
    mase: float | None = None
    accuracy: float | None
    accuracy_measured: bool
    folds: NonNegativeInt
    forecast_total: float
    current_total: float
    prior_total: float | None
    share: float | None

    scored_periods: NonNegativeInt = 0
    realized_wmape: float | None = None
    realized_actual_total: float | None = None

    @computed_field
    @property
    def value_at_risk(self) -> float | None:
        if self.wmape is None:
            return None
        return round(abs(self.forecast_total) * self.wmape / 100.0, 4)

    @computed_field
    @property
    def change_vs_prior(self) -> float | None:
        if not self.prior_total:
            return None
        return round((self.current_total - self.prior_total) / abs(self.prior_total) * 100.0, 2)


class SeriesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    group_by: list[str]
    sort: str
    total: NonNegativeInt
    limit: NonNegativeInt
    offset: NonNegativeInt
    currency: bool
    rows: list[SeriesRow]

    @computed_field
    @property
    def has_more(self) -> bool:
        return self.offset + len(self.rows) < self.total


class ScoreRequest(StrictModel):
    dataset_id: uuid.UUID | None = None


class SeriesScoreRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: uuid.UUID
    label: str
    level: NonNegativeInt
    forecast_total: float
    actual_total: float | None
    wmape: float | None
    scored_periods: NonNegativeInt
    unscored_reason: str | None

    @computed_field
    @property
    def miss(self) -> float | None:
        if self.actual_total is None:
            return None
        return round(self.forecast_total - self.actual_total, 4)


class ScorecardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    scored_at: datetime | None
    source_dataset_id: uuid.UUID | None
    source_dataset_name: str | None

    horizon: NonNegativeInt
    scored_periods: NonNegativeInt
    pending_periods: NonNegativeInt
    covered_through: date | None

    forecast_total: float
    actual_total: float
    wmape: float | None
    mae: float | None
    bias: float | None
    coverage: float | None
    confidence_level: Probability | None

    unforecast_keys: NonNegativeInt
    currency: bool
    blocked_reason: str | None
    #: Readings this run was scored against that have since been restated. The
    #: score stands as measured; this says the world moved under it.
    restated_since_scoring: NonNegativeInt = 0
    #: Cumulative error in mean absolute deviations. Near zero the misses cancel;
    #: a large value means the run missed the same way every period.
    tracking_signal: float | None = None
    drifted: bool = False
    series: list[SeriesScoreRow] = Field(default_factory=list)

    @computed_field
    @property
    def scored(self) -> bool:
        return self.scored_periods > 0

    @computed_field
    @property
    def accuracy(self) -> float | None:
        return _accuracy(self.wmape)

    @computed_field
    @property
    def intervals_held(self) -> bool | None:
        from app.forecasting.metrics import intervals_held

        return intervals_held(self.coverage, self.confidence_level)


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
    group_by: list[str]
    series_count: NonNegativeInt
    frequency: ForecastFrequency
    horizon: Horizon
    confidence_level: Probability
    aggregation: MeasureAggregation
    gap_fill: GapFill
    outlier_treatment: OutlierTreatment
    selected_model: ModelKind | None
    selection_rationale: str | None
    leading_columns: list[LeadingColumn] = Field(default_factory=list)
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
    progress_updated_at: datetime | None = None
    retry_of_run_id: uuid.UUID | None = None

    scored_at: datetime | None = None
    scored_periods: NonNegativeInt = 0
    realized_wmape: float | None = None
    realized_bias: float | None = None
    realized_coverage: float | None = None

    @computed_field
    @property
    def is_terminal(self) -> bool:
        return self.status in (RunStatus.COMPLETED, RunStatus.FAILED)

    @computed_field
    @property
    def realized_accuracy(self) -> float | None:
        return _accuracy(self.realized_wmape)


class RunStateCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all: NonNegativeInt
    completed: NonNegativeInt
    active: NonNegativeInt
    failed: NonNegativeInt


class ForecastRunPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: NonNegativeInt
    limit: NonNegativeInt
    offset: NonNegativeInt
    sort: str
    counts: RunStateCounts
    rows: list[ForecastRunRead]


class ForecastRunDetail(ForecastRunRead):
    candidates: list[ModelCandidateRead] = Field(default_factory=list)
    metrics: list[ForecastMetricRead] = Field(default_factory=list)


class ForecastMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    selected_model: ModelKind | None
    selection_rationale: str | None
    leading_columns: list[LeadingColumn] = Field(default_factory=list)
    frequency: ForecastFrequency
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
    updated_at: datetime

    @computed_field
    @property
    def percent(self) -> Percentage:
        return round(self.progress * 100.0, 2)


DriverMultiplier = Annotated[float, Field(ge=0.1, le=10.0)]


class WhatIfSimulationRequest(StrictModel):
    volume_multiplier: float = Field(default=1.0, ge=0.1, le=10.0)
    target_shift_pct: float = Field(default=0.0, ge=-90.0, le=1000.0)
    # Bounded like volume_multiplier: an unbounded dict lets a request overflow the
    # forecast to inf, which is not representable in the response.
    driver_multipliers: dict[str, DriverMultiplier] = Field(default_factory=dict, max_length=50)


class PointSimulationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: date
    baseline_forecast: float
    simulated_forecast: float
    simulated_lower_bound: float | None
    simulated_upper_bound: float | None
    simulated_best_case: float | None
    simulated_worst_case: float | None
    delta: float
    delta_pct: float


class WhatIfSimulationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    volume_multiplier: float
    target_shift_pct: float
    driver_multipliers: dict[str, float]
    baseline_total: float
    simulated_total: float
    total_delta: float
    total_delta_pct: float
    simulated_best_case_total: float
    simulated_worst_case_total: float
    #: What this simulation is, so nobody reads it as a refit. The run is
    #: re-priced under the assumption; the model is not fitted again against
    #: it, because the history under the new assumption does not exist.
    method: str
    #: How far outside the measured scenario the assumption sits, as the
    #: fraction the total was moved by. The bands widen with it.
    intervention_size: float
    points: list[PointSimulationResult]


class SavedScenarioCreate(WhatIfSimulationRequest):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)


class SavedScenarioRead(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    name: str
    description: str | None
    volume_multiplier: float
    target_shift_pct: float
    driver_multipliers: dict[str, float]
    result: WhatIfSimulationResponse
    created_at: datetime
    updated_at: datetime


class RunComparisonSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    name: str
    dataset_id: uuid.UUID
    model: ModelKind | None
    frequency: ForecastFrequency
    horizon: Horizon
    confidence_level: Probability
    forecast_total: float
    realized_accuracy: float | None
    realized_wmape: float | None
    realized_bias: float | None
    realized_coverage: float | None
    created_at: datetime


class RunMetricComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    unit: str
    left: float | None
    right: float | None
    delta: float | None
    delta_pct: float | None


class RunComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: RunComparisonSnapshot
    right: RunComparisonSnapshot
    forecast_total_delta: float
    forecast_total_delta_pct: float | None
    metrics: list[RunMetricComparison]


class ForecastMonitorItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    name: str
    status: RunStatus
    model: ModelKind | None
    completed_at: datetime | None
    forecast_end: date | None
    scored_at: datetime | None
    scored_periods: NonNegativeInt
    realized_accuracy: float | None
    realized_wmape: float | None
    realized_bias: float | None
    realized_coverage: float | None
    alert: str | None
    alert_level: str | None
    drifted: bool
    can_retry: bool


class ForecastMonitoringResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: NonNegativeInt
    healthy: NonNegativeInt
    attention: NonNegativeInt
    failed: NonNegativeInt
    active: NonNegativeInt
    drift_wmape_limit: float
    rows: list[ForecastMonitorItem]
