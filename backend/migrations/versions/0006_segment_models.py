"""Record which model forecast each segment, and whether its accuracy was measured.

Segments used to inherit the top line's accuracy figure because they were a
proportional split of it. Each one is forecast in its own right now, so the row
carries the model that won and a flag saying whether the number beside it came
from that segment's own backtest.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None

TABLES = ("regional_forecasts", "category_forecasts")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("model", sa.String(32), nullable=True))
        op.add_column(
            table,
            sa.Column(
                "accuracy_measured",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "accuracy_measured")
        op.drop_column(table, "model")
