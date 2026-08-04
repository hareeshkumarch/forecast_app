"""Persist per-run options and the queued task id.

Revision ID: 0004_run_options_and_task
Revises: 0003_llm_usage_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_run_options_and_task"
down_revision = "0003"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "forecast_runs",
        sa.Column("options", JSON_TYPE, nullable=False, server_default="{}"),
    )
    op.add_column("forecast_runs", sa.Column("task_id", sa.String(64), nullable=True))
    op.create_index("ix_forecast_runs_task_id", "forecast_runs", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_forecast_runs_task_id", table_name="forecast_runs")
    op.drop_column("forecast_runs", "task_id")
    op.drop_column("forecast_runs", "options")
