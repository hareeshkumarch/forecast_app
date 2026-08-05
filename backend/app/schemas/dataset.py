from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.datasets.queries import DEFAULT_MAX_SERIES
from app.models.enums import (
    ColumnKind,
    ColumnRole,
    DatasetStatus,
    ForecastFrequency,
    GapFill,
    IssueSeverity,
    MeasureAggregation,
)
from app.schemas.common import Identifier, NonNegativeInt, ORMModel, StrictModel

Horizon = Annotated[int, Field(ge=1, le=365)]


class DatasetColumnRead(ORMModel):
    id: uuid.UUID
    name: str
    position: NonNegativeInt
    kind: ColumnKind
    role: ColumnRole
    dtype: str
    null_count: NonNegativeInt
    distinct_count: NonNegativeInt
    min_value: str | None
    max_value: str | None
    mean_value: float | None
    sample_values: list[object]
    is_date_candidate: bool
    is_target_candidate: bool


class DatasetRead(ORMModel):
    id: uuid.UUID
    name: str
    original_filename: str | None
    source_kind: str
    connector_id: uuid.UUID | None
    status: DatasetStatus
    file_size_bytes: NonNegativeInt
    row_count: NonNegativeInt
    column_count: NonNegativeInt
    missing_value_count: NonNegativeInt
    date_range_start: date | None
    date_range_end: date | None
    time_column: str | None
    target_column: str | None
    frequency: ForecastFrequency | None
    horizon: Horizon | None
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

    @computed_field
    @property
    def max_series(self) -> int:
        """
        Maximum output series, including the pooled tail when one is needed.
        Reported rather than repeated in the client, which would promise a
        different number the day this one changes.
        """
        return DEFAULT_MAX_SERIES


class DatasetConfigureRequest(StrictModel):
    time_column: Identifier
    target_column: Identifier
    frequency: ForecastFrequency
    horizon: Horizon
    name: Identifier | None = None

    @model_validator(mode="after")
    def _time_and_target_differ(self) -> Self:
        if self.time_column == self.target_column:
            raise ValueError("The time column and the forecast target must be different columns.")
        return self


class DatasetUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: DatasetDetail
    profile: DatasetProfile

    @computed_field
    @property
    def ready_to_forecast(self) -> bool:
        return bool(self.dataset.time_column and self.dataset.target_column)


class QualityIssueRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Identifier
    severity: IssueSeverity
    message: str
    remedy: str
    count: NonNegativeInt


class DataQualityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: uuid.UUID
    time_column: Identifier
    target_column: Identifier
    frequency: ForecastFrequency
    aggregation: MeasureAggregation
    gap_fill: GapFill

    rows_scanned: NonNegativeInt
    rows_usable: NonNegativeInt
    periods_present: NonNegativeInt
    periods_expected: NonNegativeInt
    coverage: Annotated[float, Field(ge=0.0, le=1.0)]
    gap_count: NonNegativeInt
    longest_gap: NonNegativeInt
    duplicate_rows: NonNegativeInt
    partial_periods: NonNegativeInt
    outlier_periods: NonNegativeInt
    negative_periods: NonNegativeInt
    zero_periods: NonNegativeInt
    constant_target: bool
    range_start: date | None
    range_end: date | None
    fill_applied: GapFill
    blocked: bool
    issues: list[QualityIssueRead] = Field(default_factory=list)

    @computed_field
    @property
    def severity(self) -> IssueSeverity:
        if any(issue.severity is IssueSeverity.SEVERE for issue in self.issues):
            return IssueSeverity.SEVERE
        if any(issue.severity is IssueSeverity.WARNING for issue in self.issues):
            return IssueSeverity.WARNING
        return IssueSeverity.INFO
