from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "schema_mappings",
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("date_col", sa.String(length=200), nullable=False),
        sa.Column("target_col", sa.String(length=200), nullable=False),
        sa.Column("series_keys", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("covariates", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("frequency", sa.String(length=32), nullable=True),
        sa.Column("aggregation", sa.String(length=32), nullable=True),
        sa.Column("columns", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("accepted_from_dataset_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["accepted_from_dataset_id"], ["datasets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", name="uq_schema_mappings_fingerprint"),
    )
    op.create_index("ix_schema_mappings_dataset", "schema_mappings", ["accepted_from_dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_schema_mappings_dataset", table_name="schema_mappings")
    op.drop_table("schema_mappings")
