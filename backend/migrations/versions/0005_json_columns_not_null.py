
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB(), "postgresql")

COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("connectors", "config", "{}"),
    ("connector_credentials", "key_names", "[]"),
    ("dataset_columns", "sample_values", "[]"),
    ("model_candidates", "params", "{}"),
    ("forecast_drivers", "trend", "[]"),
    ("insights", "supporting_data", "{}"),
)


def upgrade() -> None:
    for table, column, empty in COLUMNS:
        op.execute(sa.text(f"UPDATE {table} SET {column} = '{empty}' WHERE {column} IS NULL"))
        op.alter_column(table, column, existing_type=JSON_TYPE, nullable=False)


def downgrade() -> None:
    for table, column, _empty in COLUMNS:
        op.alter_column(table, column, existing_type=JSON_TYPE, nullable=True)
