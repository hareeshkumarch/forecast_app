from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InsightSeverity, InsightType, ModelKind
from app.schemas.common import NonNegativeInt, ORMModel


class KpiCard(BaseModel):
    key: str
    label: str
    value: float
    display_value: str
    unit: str
    comparison_value: float | None = None
    comparison_label: str | None = None
    delta: float | None = None
    delta_display: str | None = None
    direction: str = "flat"
    tone: str = "neutral"


class BreakdownRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    label: str
    source: str
    cardinality: NonNegativeInt


class BreakdownRowRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    forecast: float
    share: float
    prior: float | None
    change: float | None
    accuracy: float | None
    accuracy_measured: bool
    actual: float | None


class BreakdownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID | None
    column: str
    label: str
    source: str
    currency: bool
    total: float
    rows: list[BreakdownRowRead] = Field(default_factory=list)


class DashboardSummary(BaseModel):
    run_id: uuid.UUID | None
    dataset_id: uuid.UUID | None
    run_name: str | None
    selected_model: ModelKind | None
    generated_at: datetime | None
    range_start: date | None
    range_end: date | None
    kpis: list[KpiCard] = Field(default_factory=list)
    has_data: bool = False
    currency_symbol: str = ""
    breakdowns: list[BreakdownRef] = Field(default_factory=list)


class DecisionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    detail: str


class DecisionHorizon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    periods: NonNegativeInt
    through: date | None
    covers_run: bool


class DecisionConcentration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: NonNegativeInt
    total: NonNegativeInt
    share: float
    leaders: list[str] = Field(default_factory=list)
    lopsided: bool


class DecisionResponse(BaseModel):
    run_id: uuid.UUID | None
    has_decision: bool = False

    grade: str | None = None
    meaning: str | None = None
    accuracy: float | None = None
    confidence_level: float | None = None

    commit: float | None = None
    base: float | None = None
    prepare: float | None = None
    spread_pct: float | None = None

    commit_display: str | None = None
    base_display: str | None = None
    prepare_display: str | None = None

    exposure: float | None = None
    downside_pct: float | None = None
    lean_pct: float | None = None

    horizon: DecisionHorizon | None = None
    concentration: DecisionConcentration | None = None
    actions: list[DecisionAction] = Field(default_factory=list)


class DriverRow(ORMModel):
    driver: str
    impact_value: float
    impact_pct: float
    change_vs_last_year: float | None
    direction: str
    trend: list
    rank: int


class DriverResponse(BaseModel):
    run_id: uuid.UUID | None
    rows: list[DriverRow] = Field(default_factory=list)


class InsightRead(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    type: InsightType
    severity: InsightSeverity
    title: str
    explanation: str
    suggested_action: str
    metric_name: str
    metric_value: float
    metric_unit: str
    supporting_data: dict
    rank: int
    generated_at: datetime
    llm_rewritten: bool


class InsightResponse(BaseModel):
    run_id: uuid.UUID | None
    items: list[InsightRead] = Field(default_factory=list)


class LlmCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_provider: str | None = Field(default=None, max_length=64)
    llm_api_key: str | None = Field(default=None, max_length=512, repr=False)
    llm_model: str | None = Field(default=None, max_length=128)
    llm_base_url: str | None = Field(default=None, max_length=512)
    llm_input_cost_per_million: float | None = Field(default=None, ge=0.0, le=100_000.0)
    llm_output_cost_per_million: float | None = Field(default=None, ge=0.0, le=100_000.0)

    def as_config(self) -> dict[str, object]:
        return self.model_dump()


class InsightRewriteRequest(LlmCredentials):
    run_id: uuid.UUID | None = None


class InsightRewriteResponse(BaseModel):
    run_id: uuid.UUID | None
    considered: NonNegativeInt = 0
    rewritten: NonNegativeInt = 0
    provider: str = ""
    model: str = ""
    summary: str = ""
    items: list[InsightRead] = Field(default_factory=list)


class LlmCheckResponse(BaseModel):
    ok: bool
    provider: str
    model: str
    latency_ms: float
    message: str
    error_code: str | None = None


class DashboardQuery(BaseModel):
    run_id: uuid.UUID | None = None
    start: date | None = None
    end: date | None = None

    view: str = "base"
