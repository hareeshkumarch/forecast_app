"""Give a series the window its prior total can be compared with.

`forecast_series.prior_total` held the window of actuals before last, with
nothing recording the last one — so the only available comparison was against
`forecast_total`, which covers the horizon rather than a full window. Every
series read as though it had collapsed by about two thirds.

Revision ID: 0008
Revises: 0007
"""

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
