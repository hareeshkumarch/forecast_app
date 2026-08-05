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


class RegionRow(ORMModel):
    region: str
    forecast_value: float
    prior_year_value: float | None
    change_vs_last_year: float | None
    accuracy: float | None
    share: float | None
    model: ModelKind | None = None
    accuracy_measured: bool = False


class RegionResponse(BaseModel):
    run_id: uuid.UUID | None
    rows: list[RegionRow] = Field(default_factory=list)
    total: float = 0.0


class CategoryRow(ORMModel):
    category: str
    forecast_value: float
    share: float
    change_vs_last_year: float | None
    accuracy: float | None
    rank: int
    model: ModelKind | None = None
    accuracy_measured: bool = False


class CategoryResponse(BaseModel):
    run_id: uuid.UUID | None
    rows: list[CategoryRow] = Field(default_factory=list)
    total: float = 0.0
    total_display: str = "—"


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


class DashboardQuery(BaseModel):
    run_id: uuid.UUID | None = None
    start: date | None = None
    end: date | None = None

    view: str = "base"
