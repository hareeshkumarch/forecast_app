from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "forecast_runs",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "forecast_runs",
        sa.Column("retry_of_run_id", sa.Uuid(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_forecast_runs_idempotency_key",
        "forecast_runs",
        ["idempotency_key"],
    )
    op.create_foreign_key(
        "fk_forecast_runs_retry_of_run_id",
        "forecast_runs",
        "forecast_runs",
        ["retry_of_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_forecast_runs_retry_of", "forecast_runs", ["retry_of_run_id"])

    op.create_table(
        "forecast_scenarios",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("volume_multiplier", sa.Float(), nullable=False, server_default="1"),
        sa.Column("target_shift_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "driver_multipliers",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("result", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "volume_multiplier >= 0.1 AND volume_multiplier <= 10",
            name="ck_forecast_scenarios_volume_multiplier",
        ),
        sa.CheckConstraint(
            "target_shift_pct >= -90 AND target_shift_pct <= 1000",
            name="ck_forecast_scenarios_target_shift",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["forecast_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_forecast_scenarios_run_created",
        "forecast_scenarios",
        ["run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_forecast_scenarios_run_created", table_name="forecast_scenarios")
    op.drop_table("forecast_scenarios")
    op.drop_index("ix_forecast_runs_retry_of", table_name="forecast_runs")
    op.drop_constraint(
        "fk_forecast_runs_retry_of_run_id",
        "forecast_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_forecast_runs_idempotency_key",
        "forecast_runs",
        type_="unique",
    )
    op.drop_column("forecast_runs", "retry_of_run_id")
    op.drop_column("forecast_runs", "idempotency_key")
