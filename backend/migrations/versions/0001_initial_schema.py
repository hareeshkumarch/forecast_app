
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
TS = sa.DateTime(timezone=True)


def _enum(name: str, *values: str) -> sa.Enum:
                                                                              
                                                
    return sa.Enum(*values, name=name, native_enum=False, length=32)


def upgrade() -> None:
                                                                             
    op.create_table(
        "connectors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "type",
            _enum(
                "connector_type",
                "postgresql",
                "mysql",
                "sqlserver",
                "csv",
                "excel",
                "rest_api",
                "bigquery",
                "snowflake",
                "redshift",
                "google_sheets",
                "salesforce",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum("connector_status", "not_configured", "configured", "connected", "error"),
            nullable=False,
        ),
        sa.Column("config", JSONB, nullable=True),
        sa.Column("last_tested_at", TS, nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_connectors_name"),
    )

    op.create_table(
        "connector_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("key_names", JSONB, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("connector_id"),
    )

                                                                             
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("original_filename", sa.String(400), nullable=True),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            _enum("dataset_status", "uploaded", "profiling", "ready", "failed"),
            nullable=False,
        ),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("missing_value_count", sa.Integer(), nullable=False),
        sa.Column("parquet_path", sa.String(600), nullable=True),
        sa.Column("raw_path", sa.String(600), nullable=True),
        sa.Column("date_range_start", sa.Date(), nullable=True),
        sa.Column("date_range_end", sa.Date(), nullable=True),
        sa.Column("time_column", sa.String(200), nullable=True),
        sa.Column("target_column", sa.String(200), nullable=True),
        sa.Column(
            "frequency",
            _enum("dataset_frequency", "daily", "weekly", "monthly", "quarterly"),
            nullable=True,
        ),
        sa.Column("horizon", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"], ondelete="SET NULL"),
    )

    op.create_table(
        "dataset_columns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            _enum("column_kind", "date", "numeric", "categorical", "boolean", "text"),
            nullable=False,
        ),
        sa.Column(
            "role",
            _enum("column_role", "time", "target", "dimension", "measure", "weight", "ignored"),
            nullable=False,
        ),
        sa.Column("dtype", sa.String(64), nullable=False),
        sa.Column("null_count", sa.Integer(), nullable=False),
        sa.Column("distinct_count", sa.Integer(), nullable=False),
        sa.Column("min_value", sa.String(200), nullable=True),
        sa.Column("max_value", sa.String(200), nullable=True),
        sa.Column("mean_value", sa.Float(), nullable=True),
        sa.Column("sample_values", JSONB, nullable=True),
        sa.Column("is_date_candidate", sa.Boolean(), nullable=False),
        sa.Column("is_target_candidate", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("dataset_id", "name", name="uq_dataset_columns_dataset_name"),
    )

                                                                             
    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "status",
            _enum("run_status", "pending", "running", "completed", "failed"),
            nullable=False,
        ),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("stage", sa.String(80), nullable=False),
        sa.Column("time_column", sa.String(200), nullable=False),
        sa.Column("target_column", sa.String(200), nullable=False),
        sa.Column("weight_column", sa.String(200), nullable=True),
        sa.Column("region_column", sa.String(200), nullable=True),
        sa.Column("category_column", sa.String(200), nullable=True),
        sa.Column(
            "frequency",
            _enum("run_frequency", "daily", "weekly", "monthly", "quarterly"),
            nullable=False,
        ),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("confidence_level", sa.Float(), nullable=False),
        sa.Column(
            "selected_model",
            _enum(
                "selected_model",
                "naive",
                "seasonal_naive",
                "holt_winters",
                "sarimax",
                "gradient_boosting",
            ),
            nullable=True,
        ),
        sa.Column("selection_rationale", sa.Text(), nullable=True),
        sa.Column("used_fallback", sa.Boolean(), nullable=False),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("history_start", sa.Date(), nullable=True),
        sa.Column("history_end", sa.Date(), nullable=True),
        sa.Column("forecast_start", sa.Date(), nullable=True),
        sa.Column("forecast_end", sa.Date(), nullable=True),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("completed_at", TS, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.CheckConstraint("horizon > 0", name="ck_forecast_runs_horizon_positive"),
    )
    op.create_index("ix_forecast_runs_status_created", "forecast_runs", ["status", "created_at"])

    op.create_table(
        "model_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "model",
            _enum(
                "candidate_model",
                "naive",
                "seasonal_naive",
                "holt_winters",
                "sarimax",
                "gradient_boosting",
            ),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("mae", sa.Float(), nullable=True),
        sa.Column("rmse", sa.Float(), nullable=True),
        sa.Column("smape", sa.Float(), nullable=True),
        sa.Column("wmape", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("folds", sa.Integer(), nullable=False),
        sa.Column("fit_seconds", sa.Float(), nullable=True),
        sa.Column("params", JSONB, nullable=True),
        sa.Column("failed", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "model", name="uq_model_candidates_run_model"),
    )

    op.create_table(
        "forecast_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(24), nullable=False),
        sa.Column("previous_value", sa.Float(), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "name", name="uq_forecast_metrics_run_name"),
    )

    op.create_table(
        "forecast_points",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("kind", _enum("point_kind", "actual", "fitted", "forecast"), nullable=False),
        sa.Column("actual", sa.Float(), nullable=True),
        sa.Column("forecast", sa.Float(), nullable=True),
        sa.Column("lower_bound", sa.Float(), nullable=True),
        sa.Column("upper_bound", sa.Float(), nullable=True),
        sa.Column("best_case", sa.Float(), nullable=True),
        sa.Column("base_case", sa.Float(), nullable=True),
        sa.Column("worst_case", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "period", "kind", name="uq_forecast_points_run_period_kind"),
    )
    op.create_index("ix_forecast_points_run_period", "forecast_points", ["run_id", "period"])

    op.create_table(
        "regional_forecasts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("region", sa.String(120), nullable=False),
        sa.Column("forecast_value", sa.Float(), nullable=False),
        sa.Column("prior_year_value", sa.Float(), nullable=True),
        sa.Column("change_vs_last_year", sa.Float(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("share", sa.Float(), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "region", name="uq_regional_forecasts_run_region"),
    )

    op.create_table(
        "category_forecasts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("forecast_value", sa.Float(), nullable=False),
        sa.Column("prior_year_value", sa.Float(), nullable=True),
        sa.Column("share", sa.Float(), nullable=False),
        sa.Column("change_vs_last_year", sa.Float(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "category", name="uq_category_forecasts_run_category"),
    )

    op.create_table(
        "forecast_drivers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("driver", sa.String(120), nullable=False),
        sa.Column("impact_value", sa.Float(), nullable=False),
        sa.Column("impact_pct", sa.Float(), nullable=False),
        sa.Column("change_vs_last_year", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("trend", JSONB, nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "driver", name="uq_forecast_drivers_run_driver"),
    )

                                                                             
    op.create_table(
        "insights",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            _enum(
                "insight_type",
                "accuracy_change",
                "forecast_gap",
                "regional_growth",
                "category_decline",
                "anomaly",
                "confidence_widening",
                "worst_case_risk",
                "driver_positive",
                "driver_negative",
                "recommendation",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            _enum("insight_severity", "positive", "info", "warning", "critical"),
            nullable=False,
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.Text(), nullable=False),
        sa.Column("metric_name", sa.String(80), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("metric_unit", sa.String(24), nullable=False),
        sa.Column("supporting_data", JSONB, nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("generated_at", TS, nullable=False),
        sa.Column("llm_rewritten", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_insights_run_rank", "insights", ["run_id", "rank"])

    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("format", _enum("export_format", "csv", "xlsx", "json"), nullable=False),
        sa.Column("status", _enum("export_status", "pending", "ready", "failed"), nullable=False),
        sa.Column("file_path", sa.String(600), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    for table in (
        "export_jobs",
        "insights",
        "forecast_drivers",
        "category_forecasts",
        "regional_forecasts",
        "forecast_points",
        "forecast_metrics",
        "model_candidates",
        "forecast_runs",
        "dataset_columns",
        "datasets",
        "connector_credentials",
        "connectors",
    ):
        op.drop_table(table)
