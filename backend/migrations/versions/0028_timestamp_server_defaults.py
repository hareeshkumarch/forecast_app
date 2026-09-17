from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | None = None
depends_on: str | None = None

TABLES = ("forecast_series", "forecast_scenarios", "schema_mappings", "app_users")
COLUMNS = ("created_at", "updated_at")


def upgrade() -> None:
    for table in TABLES:
        for column in COLUMNS:
            op.alter_column(table, column, server_default=sa.text("now()"))


def downgrade() -> None:
    for table in TABLES:
        for column in COLUMNS:
            op.alter_column(table, column, server_default=None)
