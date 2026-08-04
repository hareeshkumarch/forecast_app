from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=32)


def upgrade() -> None:
    op.add_column(
        "forecast_runs",
        sa.Column(
            "aggregation",
            _enum("measure_aggregation", "sum", "mean", "median", "last", "min", "max"),
            nullable=False,
            server_default="sum",
        ),
    )
    op.add_column(
        "forecast_runs",
        sa.Column(
            "gap_fill",
            _enum("gap_fill", "auto", "interpolate", "zero", "none"),
            nullable=False,
            server_default="auto",
        ),
    )
    op.add_column(
        "forecast_runs",
        sa.Column(
            "outlier_treatment",
            _enum("outlier_treatment", "none", "winsorise"),
            nullable=False,
            server_default="none",
        ),
    )


def downgrade() -> None:
    for column in ("outlier_treatment", "gap_fill", "aggregation"):
        op.drop_column("forecast_runs", column)
