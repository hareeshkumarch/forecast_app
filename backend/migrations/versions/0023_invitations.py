from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # An invitation is an account that exists before anybody has signed in to
    # it, so there is no subject claim to record yet. It is filled in when the
    # person arrives and the row is matched to them by email.
    op.alter_column("app_users", "subject", existing_type=sa.String(length=200), nullable=True)

    op.add_column("app_users", sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("app_users", sa.Column("invited_by", sa.String(length=320), nullable=True))

    # Email has to be unique now that it is what an invitation is matched on.
    # Two rows for one address would make which invitation gets claimed a
    # matter of row order.
    op.create_unique_constraint("uq_app_users_email", "app_users", ["email"])


def downgrade() -> None:
    op.drop_constraint("uq_app_users_email", "app_users", type_="unique")
    op.drop_column("app_users", "invited_by")
    op.drop_column("app_users", "invited_at")
    op.alter_column("app_users", "subject", existing_type=sa.String(length=200), nullable=False)
