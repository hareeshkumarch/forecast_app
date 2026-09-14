"""Give four tables the created_at/updated_at defaults their models promise.

TimestampMixin declares server_default=func.now() on both columns, and thirteen
tables were created with it. These four were not. `alembic check` cannot see the
difference because env.py compares types and not server defaults, so a green CI
— including a full downgrade and re-upgrade — never had a chance of catching it.

Nothing is broken today: the ORM supplies a Python-side default on every write,
and the application issues no raw INSERT. It bites the first time anyone writes
to these tables outside the ORM — granting access by hand, a repair script, a
COPY-based backfill — and it bites with a not-null violation on precisely the
four tables where it would be least expected.

Revision ID: 0028
Revises: 0027
"""

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
