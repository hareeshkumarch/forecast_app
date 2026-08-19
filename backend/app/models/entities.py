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
    AccessStatus,
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
    SeriesStatus,
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

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )

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
    intake: Mapped[dict] = mapped_column(JSONType, default=dict)
    #: Who uploaded this, when anybody was signed in. Nullable because every
    #: row that predates sign-in has no answer, and inventing one would be a
    #: worse record than admitting the gap.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )

    connector: Mapped[Connector | None] = relationship(back_populates="datasets")
    columns: Mapped[list[DatasetColumn]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="DatasetColumn.position"
    )
    runs: Mapped[list[ForecastRun]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        foreign_keys="ForecastRun.dataset_id",
    )

    __table_args__ = (
        Index("ix_datasets_created", "created_at"),
        Index("ix_datasets_connector", "connector_id"),
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

    #: How the raw text was read when it was not already the right type —
    #: "currency", "european", "MM/DD/YYYY", "Excel serial". Stored so the
    #: reading a run was built on stays visible after the upload screen.
    parsed_as: Mapped[str | None] = mapped_column(String(40))

    is_date_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    is_target_candidate: Mapped[bool] = mapped_column(Boolean, default=False)

    dataset: Mapped[Dataset] = relationship(back_populates="columns")

    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_dataset_columns_dataset_name"),
    )


class ForecastRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "forecast_runs"

    #: Who started this run, when anybody was signed in. Nullable for the same
    #: reason as on datasets.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )

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

    group_by: Mapped[list] = mapped_column(JSONType, default=list)
    series_count: Mapped[int] = mapped_column(Integer, default=0)

    leading_columns: Mapped[list] = mapped_column(JSONType, default=list)

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

    options: Mapped[dict] = mapped_column(JSONType, default=dict)
    task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    retry_of_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="SET NULL")
    )

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

    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scored_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL")
    )
    scored_periods: Mapped[int] = mapped_column(Integer, default=0)
    scored_through: Mapped[date | None] = mapped_column(Date)
    realized_wmape: Mapped[float | None] = mapped_column(Float)
    realized_mae: Mapped[float | None] = mapped_column(Float)
    realized_bias: Mapped[float | None] = mapped_column(Float)
    realized_coverage: Mapped[float | None] = mapped_column(Float)

    dataset: Mapped[Dataset] = relationship(back_populates="runs", foreign_keys=[dataset_id])
    candidates: Mapped[list[ModelCandidate]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    metrics: Mapped[list[ForecastMetric]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    points: Mapped[list[ForecastPoint]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ForecastPoint.period"
    )
    series: Mapped[list[ForecastSeries]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ForecastSeries.level"
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
    scenarios: Mapped[list[ForecastScenario]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ForecastScenario.created_at"
    )

    __table_args__ = (
        CheckConstraint("horizon > 0", name="ck_forecast_runs_horizon_positive"),
        UniqueConstraint("idempotency_key", name="uq_forecast_runs_idempotency_key"),
        Index("ix_forecast_runs_status_created", "status", "created_at"),
        Index("ix_forecast_runs_dataset_created", "dataset_id", "created_at"),
        Index(
            "ix_forecast_runs_completed_lookup",
            "status",
            "completed_at",
            "created_at",
        ),
        Index("ix_forecast_runs_scored_dataset", "scored_dataset_id"),
        Index("ix_forecast_runs_retry_of", "retry_of_run_id"),
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
    mase: Mapped[float | None] = mapped_column(Float)
    winkler: Mapped[float | None] = mapped_column(Float)
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


class ForecastSeries(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "forecast_series"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("forecast_series.id", ondelete="CASCADE")
    )
    level: Mapped[int] = mapped_column(Integer, default=0)

    key: Mapped[dict] = mapped_column(JSONType, default=dict)
    label: Mapped[str] = mapped_column(String(400), nullable=False)

    status: Mapped[SeriesStatus] = mapped_column(
        _enum(SeriesStatus, "series_status"), default=SeriesStatus.FORECAST
    )
    blocked_reason: Mapped[str | None] = mapped_column(Text)

    model: Mapped[ModelKind | None] = mapped_column(_enum(ModelKind, "series_model"))
    wmape: Mapped[float | None] = mapped_column(Float)
    mase: Mapped[float | None] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float)
    accuracy_measured: Mapped[bool] = mapped_column(Boolean, default=False)
    folds: Mapped[int] = mapped_column(Integer, default=0)

    forecast_total: Mapped[float] = mapped_column(Float, default=0.0)
    current_total: Mapped[float] = mapped_column(Float, default=0.0)
    prior_total: Mapped[float | None] = mapped_column(Float)
    share: Mapped[float | None] = mapped_column(Float)

    scored_periods: Mapped[int] = mapped_column(Integer, default=0)
    realized_wmape: Mapped[float | None] = mapped_column(Float)
    realized_actual_total: Mapped[float | None] = mapped_column(Float)

    run: Mapped[ForecastRun] = relationship(back_populates="series")
    children: Mapped[list[ForecastSeries]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped[ForecastSeries | None] = relationship(
        back_populates="children", remote_side="ForecastSeries.id"
    )

    __table_args__ = (
        Index("ix_forecast_series_run_level", "run_id", "level"),
        Index("ix_forecast_series_parent", "parent_id"),
    )


class ForecastPoint(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "forecast_points"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("forecast_series.id", ondelete="CASCADE")
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
        UniqueConstraint(
            "run_id",
            "series_id",
            "period",
            "kind",
            name="uq_forecast_points_run_series_period_kind",
        ),
        Index("ix_forecast_points_run_period", "run_id", "period"),
        Index("ix_forecast_points_run_series_period", "run_id", "series_id", "period"),
    )


class ActualObservation(UUIDPrimaryKeyMixin, Base):
    """What a period turned out to be, as read on a particular day.

    A restatement does not overwrite the earlier reading — it adds a row with a
    later `revised_at`. Both survive, so "what did the model know when it was
    scored" and "what do we believe now" stay separable questions. Overwriting
    makes a forecast look better or worse than it was against a number that did
    not exist when it was issued, and leaves nothing behind to show it.

    Keyed on the series rather than on a run: an actual is a fact about the
    world, and every run over the same grain is scored against the same one.
    """

    __tablename__ = "actual_observations"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    #: The grain this observation belongs to, canonicalised. Empty for the
    #: whole-business total.
    series_key: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    revised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The upload this reading came out of, when it came from one.
    source_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL")
    )

    dataset: Mapped[Dataset] = relationship(foreign_keys=[dataset_id])

    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "series_key",
            "target_date",
            "revised_at",
            name="uq_actual_observations_reading",
        ),
        Index("ix_actual_observations_lookup", "dataset_id", "series_key", "target_date"),
        Index("ix_actual_observations_revised", "dataset_id", "revised_at"),
        Index("ix_actual_observations_source_dataset", "source_dataset_id"),
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
    model: Mapped[ModelKind | None] = mapped_column(_enum(ModelKind, "segment_model"))
    accuracy_measured: Mapped[bool] = mapped_column(Boolean, default=False)
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
    model: Mapped[ModelKind | None] = mapped_column(_enum(ModelKind, "segment_model"))
    accuracy_measured: Mapped[bool] = mapped_column(Boolean, default=False)
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


class ForecastScenario(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named, reproducible what-if view over an issued forecast.

    Results are stored with the assumptions so a planning decision does not
    silently change when the same run is opened later. The source forecast is
    append-only; scenarios are separate overlays and never mutate it.
    """

    __tablename__ = "forecast_scenarios"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    volume_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    target_shift_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    driver_multipliers: Mapped[dict] = mapped_column(JSONType, default=dict)
    result: Mapped[dict] = mapped_column(JSONType, default=dict)

    run: Mapped[ForecastRun] = relationship(back_populates="scenarios")

    __table_args__ = (
        CheckConstraint(
            "volume_multiplier >= 0.1 AND volume_multiplier <= 10",
            name="ck_forecast_scenarios_volume_multiplier",
        ),
        CheckConstraint(
            "target_shift_pct >= -90 AND target_shift_pct <= 1000",
            name="ck_forecast_scenarios_target_shift",
        ),
        Index("ix_forecast_scenarios_run_created", "run_id", "created_at"),
    )


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

    source_title: Mapped[str] = mapped_column(Text, nullable=False)
    source_explanation: Mapped[str] = mapped_column(Text, nullable=False)
    source_action: Mapped[str] = mapped_column(Text, nullable=False)

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

    __table_args__ = (Index("ix_export_jobs_run", "run_id"),)


class SchemaMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "schema_mappings"

    #: Sorted column names and dtypes, hashed. The same export run again next
    #: month arrives with the same fingerprint and is mapped without asking.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    date_col: Mapped[str] = mapped_column(String(200), nullable=False)
    target_col: Mapped[str] = mapped_column(String(200), nullable=False)
    series_keys: Mapped[list] = mapped_column(JSONType, default=list)
    covariates: Mapped[list] = mapped_column(JSONType, default=list)
    frequency: Mapped[ForecastFrequency | None] = mapped_column(
        _enum(ForecastFrequency, "mapping_frequency")
    )
    aggregation: Mapped[MeasureAggregation | None] = mapped_column(
        _enum(MeasureAggregation, "mapping_aggregation")
    )
    columns: Mapped[dict] = mapped_column(JSONType, default=dict)
    accepted_from_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_schema_mappings_fingerprint"),
        Index("ix_schema_mappings_dataset", "accepted_from_dataset_id"),
    )


class AppUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Somebody who has signed in, recorded on the way past.

    Deliberately not the authority on identity — Supabase is, and this table
    holds no password, no token and nothing that could authenticate anybody.
    It exists so the platform can say who uploaded a file and who started a
    run, which nothing in the schema could answer before.
    """

    __tablename__ = "app_users"

    #: The `sub` claim: stable for the life of the account, unlike the email.
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    picture_url: Mapped[str | None] = mapped_column(String(600))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[AccessStatus] = mapped_column(
        _enum(AccessStatus, "access_status"), default=AccessStatus.PENDING, nullable=False
    )
    #: Who decided, and when. Kept because "why does this person have access?"
    #: is a question that gets asked months later, and an audit trail nobody
    #: wrote down is one nobody can answer.
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(320))
    #: When the request to approve them was last emailed out, so a reminder can
    #: be sent without spamming on every page load.
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("subject", name="uq_app_users_subject"),
        Index("ix_app_users_email", "email"),
    )
