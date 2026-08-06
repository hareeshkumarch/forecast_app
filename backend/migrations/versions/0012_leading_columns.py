"""Record which of the customer's own columns the forecast read.

The profiler has been labelling every spare numeric column a measure since the
first upload, and nothing ever read them — a price, a promotion flag or a
traffic count sitting beside the target was ignored however much it explained.
Now a run can use them, and this is where it says which ones it used and how
far ahead each one leads, so the answer is data rather than a sentence someone
has to parse back out of the rationale.

Empty is the ordinary case and means the same thing it always did: the forecast
came from the target's own history.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.entities import JSONType

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forecast_runs",
        sa.Column("leading_columns", JSONType, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("forecast_runs", "leading_columns")
