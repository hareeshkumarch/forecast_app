from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The welcome email is gone, so the stamp that suppressed a second one is too.

    An approved account collected three messages saying a version of the same
    thing — an acknowledgement when it asked, the approval, and a welcome on
    first sign-in. The approval is now the whole of it, and this column exists
    only to stop a mail nobody sends. A column nothing reads and nothing writes
    is a question for whoever opens the schema next, so it goes rather than
    lingering as one.
    """
    op.drop_column("app_users", "welcomed_at")


def downgrade() -> None:
    op.add_column("app_users", sa.Column("welcomed_at", sa.DateTime(timezone=True), nullable=True))
