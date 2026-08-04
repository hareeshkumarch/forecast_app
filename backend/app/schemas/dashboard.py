from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import InsightSeverity, InsightType, ModelKind
from app.schemas.common import ORMModel


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


class RegionRow(ORMModel):
    region: str
    forecast_value: float
    prior_year_value: float | None
    change_vs_last_year: float | None
    accuracy: float | None
    share: float | None


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
