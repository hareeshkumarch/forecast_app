"""Persist per-run options and the queued task id.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

<<<<<<< HEAD
revision = "0004_run_options_and_task"
down_revision = "0003"
=======
revision: str = "0004"
down_revision: str | None = "0003"
>>>>>>> d328f9f34baed9668a93295aba656955bba6b3f5
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
