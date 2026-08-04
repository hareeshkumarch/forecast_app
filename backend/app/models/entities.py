from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ColumnKind,
    ColumnRole,
    ConnectorStatus,
    ConnectorType,
    DatasetStatus,
    ExportFormat,
    ExportStatus,
    ForecastFrequency,
    GapFill,
    InsightSeverity,
    InsightType,
    MeasureAggregation,
    ModelKind,
    OutlierTreatment,
    PointKind,
    RunStatus,
)

JSONType = JSON().with_variant(JSONB(), "postgresql")


class RobustEnum(TypeDecorator[Any]):
    impl = String(32)
    cache_ok = True

    def __init__(self, enum_cls: type[Enum], _name: str | None = None) -> None:
        self.enum_cls = enum_cls
        super().__init__()

    def process_bind_param(self, value: Any, _dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return str(value.value)
        return str(value)

    def process_result_value(self, value: Any, _dialect: Dialect) -> Any:
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value
        try:
            return self.enum_cls(value)
        except ValueError:
            pass
        try:
            return self.enum_cls[value]
        except KeyError:
            pass
        val_str = str(value).lower()
        for member in self.enum_cls:
            if member.value.lower() == val_str or member.name.lower() == val_str:
                return member
        raise LookupError(
            f"'{value}' is not among defined enum values for {self.enum_cls.__name__}"
        )


def _enum(enum_cls: type, name: str) -> RobustEnum:
    return RobustEnum(enum_cls, name)


class Connector(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connectors"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[ConnectorType] = mapped_column(_enum(ConnectorType, "connector_type"))
    status: Mapped[ConnectorStatus] = mapped_column(
        _enum(ConnectorStatus, "connector_status"), default=ConnectorStatus.NOT_CONFIGURED
    )

    config: Mapped[dict] = mapped_column(JSONType, default=dict)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    credential: Mapped[ConnectorCredential | None] = relationship(
        back_populates="connector", cascade="all, delete-orphan", uselist=False
    )
    datasets: Mapped[list[Dataset]] = relationship(back_populates="connector")

    __table_args__ = (UniqueConstraint("name", name="uq_connectors_name"),)


class ConnectorCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connector_credentials"

    connector_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)

    key_names: Mapped[list] = mapped_column(JSONType, default=list)

    connector: Mapped[Connector] = relationship(back_populates="credential")


class Dataset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "datasets"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(400))
    source_kind: Mapped[str] = mapped_column(String(32), default="upload")
    connector_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("connectors.id", ondelete="SET NULL")
    )
    status: Mapped[DatasetStatus] = mapped_column(
        _enum(DatasetStatus, "dataset_status"), default=DatasetStatus.UPLOADED
    )

    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_value_count: Mapped[int] = mapped_column(Integer, default=0)

    parquet_path: Mapped[str | None] = mapped_column(String(600))
    raw_path: Mapped[str | None] = mapped_column(String(600))

    date_range_start: Mapped[date | None] = mapped_column(Date)
    date_range_end: Mapped[date | None] = mapped_column(Date)

    time_column: Mapped[str | None] = mapped_column(String(200))
    target_column: Mapped[str | None] = mapped_column(String(200))
    frequency: Mapped[ForecastFrequency | None] = mapped_column(
        _enum(ForecastFrequency, "dataset_frequency")
    )
    horizon: Mapped[int | None] = mapped_column(Integer)

    error_message: Mapped[str | None] = mapped_column(Text)

    connector: Mapped[Connector | None] = relationship(back_populates="datasets")
    columns: Mapped[list[DatasetColumn]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="DatasetColumn.position"
    )
    runs: Mapped[list[ForecastRun]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class DatasetColumn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dataset_columns"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[ColumnKind] = mapped_column(_enum(ColumnKind, "column_kind"))
    role: Mapped[ColumnRole] = mapped_column(
        _enum(ColumnRole, "column_role"), default=ColumnRole.IGNORED
    )
    dtype: Mapped[str] = mapped_column(String(64), default="unknown")

    null_count: Mapped[int] = mapped_column(Integer, default=0)
    distinct_count: Mapped[int] = mapped_column(Integer, default=0)
    min_value: Mapped[str | None] = mapped_column(String(200))
    max_value: Mapped[str | None] = mapped_column(String(200))
    mean_value: Mapped[float | None] = mapped_column(Float)
    sample_values: Mapped[list] = mapped_column(JSONType, default=list)

    is_date_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    is_target_candidate: Mapped[bool] = mapped_column(Boolean, default=False)

    dataset: Mapped[Dataset] = relationship(back_populates="columns")

    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_dataset_columns_dataset_name"),
    )


class ForecastRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "forecast_runs"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        _enum(RunStatus, "run_status"), default=RunStatus.PENDING
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(80), default="queued")

    time_column: Mapped[str] = mapped_column(String(200), nullable=False)
    target_column: Mapped[str] = mapped_column(String(200), nullable=False)
    weight_column: Mapped[str | None] = mapped_column(String(200))
    region_column: Mapped[str | None] = mapped_column(String(200))
    category_column: Mapped[str | None] = mapped_column(String(200))

    frequency: Mapped[ForecastFrequency] = mapped_column(_enum(ForecastFrequency, "run_frequency"))
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_level: Mapped[float] = mapped_column(Float, default=0.8)
    aggregation: Mapped[MeasureAggregation] = mapped_column(
        _enum(MeasureAggregation, "measure_aggregation"), default=MeasureAggregation.SUM
    )
    gap_fill: Mapped[GapFill] = mapped_column(_enum(GapFill, "gap_fill"), default=GapFill.AUTO)
    outlier_treatment: Mapped[OutlierTreatment] = mapped_column(
        _enum(OutlierTreatment, "outlier_treatment"), default=OutlierTreatment.NONE
    )

    # Per-run tuning choices, stored so a worker in another process — or the
    # same one after a restart — fits the run the caller actually asked for.
    # Any LLM key is encrypted before it lands here.
    options: Mapped[dict] = mapped_column(JSONType, default=dict)
    task_id: Mapped[str | None] = mapped_column(String(64), index=True)

    selected_model: Mapped[ModelKind | None] = mapped_column(_enum(ModelKind, "selected_model"))
    selection_rationale: Mapped[str | None] = mapped_column(Text)

    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(Text)

    history_start: Mapped[date | None] = mapped_column(Date)
    history_end: Mapped[date | None] = mapped_column(Date)
    forecast_start: Mapped[date | None] = mapped_column(Date)
    forecast_end: Mapped[date | None] = mapped_column(Date)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    dataset: Mapped[Dataset] = relationship(back_populates="runs")
    candidates: Mapped[list[ModelCandidate]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    metrics: Mapped[list[ForecastMetric]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    points: Mapped[list[ForecastPoint]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ForecastPoint.period"
    )
    regional: Mapped[list[RegionalForecast]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    categories: Mapped[list[CategoryForecast]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    drivers: Mapped[list[ForecastDriver]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    insights: Mapped[list[Insight]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    llm_usage_events: Mapped[list[LlmUsageEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    exports: Mapped[list[ExportJob]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("horizon > 0", name="ck_forecast_runs_horizon_positive"),
        Index("ix_forecast_runs_status_created", "status", "created_at"),
    )


class ModelCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_candidates"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[ModelKind] = mapped_column(_enum(ModelKind, "candidate_model"))
    rank: Mapped[int] = mapped_column(Integer, default=0)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)

    mae: Mapped[float | None] = mapped_column(Float)
    rmse: Mapped[float | None] = mapped_column(Float)
    smape: Mapped[float | None] = mapped_column(Float)
    wmape: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)

    folds: Mapped[int] = mapped_column(Integer, default=0)
    fit_seconds: Mapped[float | None] = mapped_column(Float)
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    failed: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    run: Mapped[ForecastRun] = relationship(back_populates="candidates")

    __table_args__ = (UniqueConstraint("run_id", "model", name="uq_model_candidates_run_model"),)


class ForecastMetric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "forecast_metrics"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="absolute")

    previous_value: Mapped[float | None] = mapped_column(Float)

    run: Mapped[ForecastRun] = relationship(back_populates="metrics")

    __table_args__ = (UniqueConstraint("run_id", "name", name="uq_forecast_metrics_run_name"),)


class ForecastPoint(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "forecast_points"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[PointKind] = mapped_column(_enum(PointKind, "point_kind"))

    actual: Mapped[float | None] = mapped_column(Float)
    forecast: Mapped[float | None] = mapped_column(Float)
    lower_bound: Mapped[float | None] = mapped_column(Float)
    upper_bound: Mapped[float | None] = mapped_column(Float)
    best_case: Mapped[float | None] = mapped_column(Float)
    base_case: Mapped[float | None] = mapped_column(Float)
    worst_case: Mapped[float | None] = mapped_column(Float)

    run: Mapped[ForecastRun] = relationship(back_populates="points")

    __table_args__ = (
        UniqueConstraint("run_id", "period", "kind", name="uq_forecast_points_run_period_kind"),
        Index("ix_forecast_points_run_period", "run_id", "period"),
    )


class RegionalForecast(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "regional_forecasts"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    region: Mapped[str] = mapped_column(String(120), nullable=False)
    forecast_value: Mapped[float] = mapped_column(Float, nullable=False)
    prior_year_value: Mapped[float | None] = mapped_column(Float)
    change_vs_last_year: Mapped[float | None] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float)
    share: Mapped[float | None] = mapped_column(Float)

    run: Mapped[ForecastRun] = relationship(back_populates="regional")

    __table_args__ = (
        UniqueConstraint("run_id", "region", name="uq_regional_forecasts_run_region"),
    )


class CategoryForecast(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "category_forecasts"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    forecast_value: Mapped[float] = mapped_column(Float, nullable=False)
    prior_year_value: Mapped[float | None] = mapped_column(Float)
    share: Mapped[float] = mapped_column(Float, default=0.0)
    change_vs_last_year: Mapped[float | None] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped[ForecastRun] = relationship(back_populates="categories")

    __table_args__ = (
        UniqueConstraint("run_id", "category", name="uq_category_forecasts_run_category"),
    )


class ForecastDriver(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "forecast_drivers"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    driver: Mapped[str] = mapped_column(String(120), nullable=False)
    impact_value: Mapped[float] = mapped_column(Float, nullable=False)
    impact_pct: Mapped[float] = mapped_column(Float, default=0.0)
    change_vs_last_year: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(16), default="flat")

    trend: Mapped[list] = mapped_column(JSONType, default=list)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[str] = mapped_column(String(64), default="decomposition")

    run: Mapped[ForecastRun] = relationship(back_populates="drivers")

    __table_args__ = (UniqueConstraint("run_id", "driver", name="uq_forecast_drivers_run_driver"),)


class Insight(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "insights"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[InsightType] = mapped_column(_enum(InsightType, "insight_type"))
    severity: Mapped[InsightSeverity] = mapped_column(_enum(InsightSeverity, "insight_severity"))
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str] = mapped_column(Text, nullable=False)

    metric_name: Mapped[str] = mapped_column(String(80), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    metric_unit: Mapped[str] = mapped_column(String(24), default="absolute")
    supporting_data: Mapped[dict] = mapped_column(JSONType, default=dict)

    rank: Mapped[int] = mapped_column(Integer, default=0)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    llm_rewritten: Mapped[bool] = mapped_column(Boolean, default=False)

    run: Mapped[ForecastRun] = relationship(back_populates="insights")

    __table_args__ = (Index("ix_insights_run_rank", "run_id", "rank"),)


class LlmUsageEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One provider request, without credentials or prompt contents."""

    __tablename__ = "llm_usage_events"

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=True
    )
    purpose: Mapped[str] = mapped_column(String(64), default="insight_rewrite")
    insight_type: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)

    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)

    latency_ms: Mapped[float | None] = mapped_column(Float)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    cost_source: Mapped[str] = mapped_column(String(24), default="unavailable")
    error_code: Mapped[str | None] = mapped_column(String(80))

    run: Mapped[ForecastRun | None] = relationship(back_populates="llm_usage_events")

    __table_args__ = (
        Index("ix_llm_usage_created", "created_at"),
        Index("ix_llm_usage_provider_model", "provider", "model"),
        Index("ix_llm_usage_run", "run_id"),
    )


class ExportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "export_jobs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[ExportFormat] = mapped_column(_enum(ExportFormat, "export_format"))
    status: Mapped[ExportStatus] = mapped_column(
        _enum(ExportStatus, "export_status"), default=ExportStatus.PENDING
    )
    file_path: Mapped[str | None] = mapped_column(String(600))
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[ForecastRun] = relationship(back_populates="exports")
