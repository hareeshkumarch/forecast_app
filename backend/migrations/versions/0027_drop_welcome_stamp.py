from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("app_users", "welcomed_at")


def downgrade() -> None:
    op.add_column("app_users", sa.Column("welcomed_at", sa.DateTime(timezone=True), nullable=True))
