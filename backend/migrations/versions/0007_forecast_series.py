"""Give a run many forecastable series instead of exactly one.

A run used to aggregate its whole dataset into a single line. It can now be
asked for a grain — SKU by store, account by product — and forecasts every
combination, so `forecast_series` holds the tree and every point says which
series it belongs to.

`series_id` is nullable on purpose: NULL still means the run's own top line, so
every run made before this migration stays valid and every dashboard query that
reads points keeps working untouched.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "forecast_runs",
        sa.Column("group_by", JSON_TYPE, nullable=False, server_default="[]"),
    )
    op.add_column(
        "forecast_runs",
        sa.Column("series_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "forecast_series",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("forecast_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("forecast_series.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("key", JSON_TYPE, nullable=False, server_default="{}"),
        sa.Column("label", sa.String(400), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="forecast"),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("model", sa.String(32), nullable=True),
        sa.Column("wmape", sa.Float(), nullable=True),
        sa.Column("mase", sa.Float(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("accuracy_measured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("folds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("forecast_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("prior_total", sa.Float(), nullable=True),
        sa.Column("share", sa.Float(), nullable=True),
    )
    op.create_index("ix_forecast_series_run_level", "forecast_series", ["run_id", "level"])
    op.create_index("ix_forecast_series_parent", "forecast_series", ["parent_id"])

    op.add_column(
        "forecast_points",
        sa.Column(
            "series_id",
            sa.Uuid(),
            sa.ForeignKey("forecast_series.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_forecast_points_run_series_period",
        "forecast_points",
        ["run_id", "series_id", "period"],
    )

    # The old key would have let a run store only its first series; every later
    # one would collide on the same period.
    op.drop_constraint(
        "uq_forecast_points_run_period_kind", "forecast_points", type_="unique"
    )
    op.create_unique_constraint(
        "uq_forecast_points_run_series_period_kind",
        "forecast_points",
        ["run_id", "series_id", "period", "kind"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_forecast_points_run_series_period_kind", "forecast_points", type_="unique"
    )
    op.create_unique_constraint(
        "uq_forecast_points_run_period_kind", "forecast_points", ["run_id", "period", "kind"]
    )
    op.drop_index("ix_forecast_points_run_series_period", table_name="forecast_points")
    op.drop_column("forecast_points", "series_id")

    op.drop_index("ix_forecast_series_parent", table_name="forecast_series")
    op.drop_index("ix_forecast_series_run_level", table_name="forecast_series")
    op.drop_table("forecast_series")

    op.drop_column("forecast_runs", "series_count")
    op.drop_column("forecast_runs", "group_by")
