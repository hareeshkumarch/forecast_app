"""Actuals kept as a revision history rather than a single current value.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "actual_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("series_key", sa.String(600), nullable=False, server_default=""),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("revised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "series_key",
            "target_date",
            "revised_at",
            name="uq_actual_observations_reading",
        ),
    )
    op.create_index(
        "ix_actual_observations_lookup",
        "actual_observations",
        ["dataset_id", "series_key", "target_date"],
    )
    op.create_index(
        "ix_actual_observations_revised",
        "actual_observations",
        ["dataset_id", "revised_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_actual_observations_revised", table_name="actual_observations")
    op.drop_index("ix_actual_observations_lookup", table_name="actual_observations")
    op.drop_table("actual_observations")
