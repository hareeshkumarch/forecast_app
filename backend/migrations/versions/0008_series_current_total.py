
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forecast_series",
        sa.Column("current_total", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("forecast_series", "current_total")
