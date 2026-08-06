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
    """One way this run's forecast can be split, named as the customer named it."""

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
    #: Which splits this run can offer. Empty for a dataset with no dimensions,
    #: which is a real answer and not a gap to paper over with blank panels.
    breakdowns: list[BreakdownRef] = Field(default_factory=list)


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
    """
    A provider to talk to, for this request only.

    Nothing here is stored: the key lives in the caller's browser and is sent
    with the request that needs it, so the server never holds a credential it
    was not handed. Omitting them all falls back to the server's own settings.
    """

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
    """What the rewriter did, in words the person who pressed the button reads."""

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
