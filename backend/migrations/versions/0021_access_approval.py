from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows are approved, not pending. Anyone already in the table
    # signed in during the window before approval existed and was let through
    # then; turning that into a queue of retrospective requests would lock out
    # people who already had access.
    op.add_column(
        "app_users",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="approved"),
    )
    op.add_column("app_users", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("app_users", sa.Column("decided_by", sa.String(length=320), nullable=True))
    op.add_column(
        "app_users", sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_app_users_status", "app_users", ["status"])

    # New rows decide their own status in the application, where the admin list
    # and the approval switch are both readable.
    op.alter_column("app_users", "status", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_app_users_status", table_name="app_users")
    for column in ("requested_at", "decided_by", "decided_at", "status"):
        op.drop_column("app_users", column)
