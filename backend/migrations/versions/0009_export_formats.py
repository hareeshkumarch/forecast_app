"""Offer CSV and PDF exports rather than CSV, Excel and JSON.

A CSV is for numbers that will be worked on further and a PDF is for numbers
that will be read; a spreadsheet and a JSON dump sat between the two without
serving either well.

Export jobs are cached artifacts rather than user data — each row points at a
generated file — so rows in the retired formats are dropped rather than
relabelled, which would have left them claiming to be something they are not.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels = None
depends_on = None

OLD = ("csv", "xlsx", "json")
NEW = ("csv", "pdf")
CONSTRAINT = "export_format"


def _swap(from_values: tuple[str, ...], to_values: tuple[str, ...]) -> None:
    bind = op.get_bind()
    keep = ", ".join(f"'{value}'" for value in to_values)
    bind.execute(sa.text(f"DELETE FROM export_jobs WHERE format NOT IN ({keep})"))

    # The column is a VARCHAR guarded by a CHECK; on SQLite the constraint is
    # part of the table definition, so the whole column is rebuilt.
    with op.batch_alter_table("export_jobs") as batch:
        batch.alter_column(
            "format",
            existing_type=sa.String(32),
            type_=sa.Enum(*to_values, name=CONSTRAINT, native_enum=False, length=32),
            existing_nullable=False,
        )
    del from_values


def upgrade() -> None:
    _swap(OLD, NEW)


def downgrade() -> None:
    _swap(NEW, OLD)
