
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_candidates", sa.Column("mase", sa.Float(), nullable=True))
    op.add_column("model_candidates", sa.Column("winkler", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_candidates", "winkler")
    op.drop_column("model_candidates", "mase")
