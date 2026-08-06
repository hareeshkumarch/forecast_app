
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.entities import JSONType

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forecast_runs",
        sa.Column("leading_columns", JSONType, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("forecast_runs", "leading_columns")
