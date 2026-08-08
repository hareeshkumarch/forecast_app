from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # How a column's raw text was read — "currency", "european", "MM/DD/YYYY",
    # "Excel serial". Kept beside the column so the reading a forecast was
    # built on is still answerable once the upload screen is gone.
    op.add_column("dataset_columns", sa.Column("parsed_as", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("dataset_columns", "parsed_as")
