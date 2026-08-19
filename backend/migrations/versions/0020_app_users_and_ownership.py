from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNED_TABLES = ("datasets", "forecast_runs", "connectors")


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("picture_url", sa.String(length=600), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject", name="uq_app_users_subject"),
    )
    op.create_index("ix_app_users_email", "app_users", ["email"])

    # Nullable throughout. Every row that predates sign-in has no owner, and
    # there is no honest value to backfill one with — a column that admits the
    # gap is a better record than one that invents an answer.
    for table in OWNED_TABLES:
        op.add_column(table, sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_created_by_user_id",
            table,
            "app_users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_created_by", table, ["created_by_user_id"])


def downgrade() -> None:
    for table in OWNED_TABLES:
        op.drop_index(f"ix_{table}_created_by", table_name=table)
        op.drop_constraint(f"fk_{table}_created_by_user_id", table, type_="foreignkey")
        op.drop_column(table, "created_by_user_id")

    op.drop_index("ix_app_users_email", table_name="app_users")
    op.drop_table("app_users")
