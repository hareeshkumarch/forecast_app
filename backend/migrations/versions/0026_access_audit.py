from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("subject_email", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
    )
    op.create_index("ix_access_audit_at", "access_audit", ["at"])
    op.create_index("ix_access_audit_subject", "access_audit", ["subject_email"])


def downgrade() -> None:
    op.drop_index("ix_access_audit_subject", table_name="access_audit")
    op.drop_index("ix_access_audit_at", table_name="access_audit")
    op.drop_table("access_audit")
