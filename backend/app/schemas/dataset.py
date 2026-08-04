
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import ColumnKind, ColumnRole, DatasetStatus, ForecastFrequency
from app.schemas.common import ORMModel


class DatasetColumnRead(ORMModel):
    id: uuid.UUID
    name: str
    position: int
    kind: ColumnKind
    role: ColumnRole
    dtype: str
    null_count: int
    distinct_count: int
    min_value: str | None
    max_value: str | None
    mean_value: float | None
    sample_values: list
    is_date_candidate: bool
    is_target_candidate: bool


class DatasetRead(ORMModel):
    id: uuid.UUID
    name: str
    original_filename: str | None
    source_kind: str
    connector_id: uuid.UUID | None
    status: DatasetStatus
    file_size_bytes: int
    row_count: int
    column_count: int
    missing_value_count: int
    date_range_start: date | None
    date_range_end: date | None
    time_column: str | None
    target_column: str | None
    frequency: ForecastFrequency | None
    horizon: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DatasetDetail(DatasetRead):
    columns: list[DatasetColumnRead] = Field(default_factory=list)


class ColumnSuggestion(BaseModel):
    name: str
    kind: ColumnKind
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class DatasetProfile(BaseModel):

    dataset_id: uuid.UUID
    row_count: int
    column_count: int
    missing_value_count: int
    missing_value_pct: float
    date_range_start: date | None
    date_range_end: date | None
    detected_frequency: ForecastFrequency | None
    columns: list[DatasetColumnRead]
    time_column_suggestions: list[ColumnSuggestion]
    target_column_suggestions: list[ColumnSuggestion]
    dimension_suggestions: list[ColumnSuggestion]
    preview_rows: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DatasetConfigureRequest(BaseModel):

    time_column: str
    target_column: str
    frequency: ForecastFrequency
    horizon: int = Field(ge=1, le=365)
    name: str | None = None


class DatasetUploadResponse(BaseModel):
    dataset: DatasetDetail
    profile: DatasetProfile
