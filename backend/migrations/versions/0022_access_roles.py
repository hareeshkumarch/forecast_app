from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_users",
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
    )
    op.create_index("ix_app_users_role", "app_users", ["role"])
    # Everyone already in the table keeps the access they have; who is an
    # administrator is decided on their next sign-in from the configured list,
    # so nobody is promoted here by guesswork.
    op.alter_column("app_users", "role", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_app_users_role", table_name="app_users")
    op.drop_column("app_users", "role")
