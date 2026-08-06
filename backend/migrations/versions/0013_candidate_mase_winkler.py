"""Record how each candidate did against the free forecast, and what its bands cost.

Two metrics the roster was being ranked without.

`mase` measures a model against the seasonal-naive forecast anyone could have
made for nothing. It matters because wMAPE divides by the size of the actuals,
so a stretch of near-zero demand sends it past 100% and the platform correctly
refuses to report an accuracy at all — leaving intermittent series with a dash
and no other number. MASE has a denominator that does not collapse, so those
series get a figure that still means something. `forecast_series.mase` has
existed since the grouped-run schema and was never written; now both it and
the candidate rows carry it.

`winkler` prices the prediction interval: its width, plus a penalty for every
actual that fell outside it. Selection used to rank purely on point error, so a
model quoting a narrow band it could not keep scored identically to one that
admitted the same uncertainty out loud. Null where a run had too few folds to
size a band from folds it was not then judged on.

Revision ID: 0013
Revises: 0012
"""

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
