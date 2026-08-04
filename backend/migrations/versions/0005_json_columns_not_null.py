"""Match the JSON columns to the models that already promise a value.

The ORM types these as `Mapped[dict]` and `Mapped[list]` with a default, but
0001 created them nullable, so the database allowed a NULL the code would then
read as a dict. Existing NULLs are filled with the same empty value the ORM
default would have written.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB(), "postgresql")

# (table, column, the empty value the ORM default produces)
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
        # Inlined rather than bound: a bound parameter arrives typed as VARCHAR,
        # which Postgres will not implicitly cast to jsonb. These are fixed
        # constants from the tuple above, never user input.
        op.execute(sa.text(f"UPDATE {table} SET {column} = '{empty}' WHERE {column} IS NULL"))
        op.alter_column(table, column, existing_type=JSON_TYPE, nullable=False)


def downgrade() -> None:
    for table, column, _empty in COLUMNS:
        op.alter_column(table, column, existing_type=JSON_TYPE, nullable=True)
