from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_users", sa.Column("welcomed_at", sa.DateTime(timezone=True), nullable=True))

    # Anybody already signed in has been using this for a while and does not
    # need welcoming to it. Stamping them now is what stops the next deploy
    # mailing every existing account at once.
    op.execute(
        "UPDATE app_users SET welcomed_at = COALESCE(last_seen_at, created_at) "
        "WHERE status = 'approved'"
    )


def downgrade() -> None:
    op.drop_column("app_users", "welcomed_at")
