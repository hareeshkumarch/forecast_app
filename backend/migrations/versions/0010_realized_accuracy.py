"""Record how a forecast actually did, not just how it backtested.

Every accuracy figure stored until now comes from folds held out of the
history the model was fitted on. It is the model's expected error, and it is
not the same number as the error the forecast turned out to have. These
columns hold the second one, filled in once the periods a run covered have
been lived through and a later dataset can say what happened.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels = None
depends_on = None

RUN_COLUMNS = (
    ("realized_wmape", sa.Float()),
    ("realized_mae", sa.Float()),
    ("realized_bias", sa.Float()),
    ("realized_coverage", sa.Float()),
)

SERIES_COLUMNS = (
    ("realized_wmape", sa.Float()),
    ("realized_actual_total", sa.Float()),
)


def upgrade() -> None:
    op.add_column("forecast_runs", sa.Column("scored_at", sa.DateTime(timezone=True)))
    op.add_column("forecast_runs", sa.Column("scored_dataset_id", sa.Uuid()))
    op.add_column(
        "forecast_runs",
        sa.Column("scored_periods", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("forecast_runs", sa.Column("scored_through", sa.Date()))
    for name, kind in RUN_COLUMNS:
        op.add_column("forecast_runs", sa.Column(name, kind))

    # The dataset that supplied the actuals may be deleted later; losing the
    # provenance is survivable, losing the score with it is not.
    op.create_foreign_key(
        "fk_forecast_runs_scored_dataset",
        "forecast_runs",
        "datasets",
        ["scored_dataset_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "forecast_series",
        sa.Column("scored_periods", sa.Integer(), nullable=False, server_default="0"),
    )
    for name, kind in SERIES_COLUMNS:
        op.add_column("forecast_series", sa.Column(name, kind))


def downgrade() -> None:
    for name, _kind in SERIES_COLUMNS:
        op.drop_column("forecast_series", name)
    op.drop_column("forecast_series", "scored_periods")

    op.drop_constraint("fk_forecast_runs_scored_dataset", "forecast_runs", type_="foreignkey")
    for name, _kind in RUN_COLUMNS:
        op.drop_column("forecast_runs", name)
    op.drop_column("forecast_runs", "scored_through")
    op.drop_column("forecast_runs", "scored_periods")
    op.drop_column("forecast_runs", "scored_dataset_id")
    op.drop_column("forecast_runs", "scored_at")
