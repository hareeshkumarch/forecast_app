"""Keep the wording the platform computed, alongside the wording on screen.

The insight rewriter is a phrasing step: the numbers are computed here and the
model is only allowed to say them better. Until now the rewrite overwrote the
computed text, which made the step one-way — a key added after a run could not
be applied without refitting every model, rewriting twice fed the model its own
output, and there was no way back to the platform's own words.

These columns hold what the generators produced. The displayed columns hold
what the reader sees, which is either the same text or a rewrite of it.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels = None
depends_on = None

SOURCE_COLUMNS = ("source_title", "source_explanation", "source_action")


def upgrade() -> None:
    for name in SOURCE_COLUMNS:
        op.add_column("insights", sa.Column(name, sa.Text(), nullable=True))

    # Rows written before this migration have no separate source. Their
    # displayed text is the best record of it: for a run with no LLM it is
    # exactly the computed wording, and for one with an LLM it is at least
    # number-for-number faithful to it.
    op.execute(
        """
        UPDATE insights
           SET source_title = title,
               source_explanation = explanation,
               source_action = suggested_action
        """
    )

    for name in SOURCE_COLUMNS:
        op.alter_column("insights", name, nullable=False)


def downgrade() -> None:
    for name in reversed(SOURCE_COLUMNS):
        op.drop_column("insights", name)
