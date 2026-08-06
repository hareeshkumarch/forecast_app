
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels = None
depends_on = None

SOURCE_COLUMNS = ("source_title", "source_explanation", "source_action")


def upgrade() -> None:
    for name in SOURCE_COLUMNS:
        op.add_column("insights", sa.Column(name, sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE insights
           SET source_title = title,
               source_explanation = explanation,
               source_action = suggested_action
        """
    )

    for name in SOURCE_COLUMNS:
        op.alter_column("insights", name, nullable=False)


def downgrade() -> None:
    for name in reversed(SOURCE_COLUMNS):
        op.drop_column("insights", name)
