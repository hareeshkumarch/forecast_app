from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index the relationships and list paths used by the API.

    PostgreSQL does not automatically index foreign-key columns. These keep
    connector/dataset cleanup and the default newest/latest reads from turning
    into full-table scans as forecast history grows.
    """

    op.create_index("ix_datasets_created", "datasets", ["created_at"])
    op.create_index("ix_datasets_connector", "datasets", ["connector_id"])
    op.create_index(
        "ix_forecast_runs_dataset_created",
        "forecast_runs",
        ["dataset_id", "created_at"],
    )
    op.create_index(
        "ix_forecast_runs_completed_lookup",
        "forecast_runs",
        ["status", "completed_at", "created_at"],
    )
    op.create_index(
        "ix_forecast_runs_scored_dataset",
        "forecast_runs",
        ["scored_dataset_id"],
    )
    op.create_index(
        "ix_actual_observations_source_dataset",
        "actual_observations",
        ["source_dataset_id"],
    )
    op.create_index("ix_export_jobs_run", "export_jobs", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_export_jobs_run", table_name="export_jobs")
    op.drop_index(
        "ix_actual_observations_source_dataset",
        table_name="actual_observations",
    )
    op.drop_index("ix_forecast_runs_scored_dataset", table_name="forecast_runs")
    op.drop_index("ix_forecast_runs_completed_lookup", table_name="forecast_runs")
    op.drop_index("ix_forecast_runs_dataset_created", table_name="forecast_runs")
    op.drop_index("ix_datasets_connector", table_name="datasets")
    op.drop_index("ix_datasets_created", table_name="datasets")
