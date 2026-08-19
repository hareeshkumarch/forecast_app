from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import polars as pl

from app.datasets.quality import expected_periods
from app.models.enums import ForecastFrequency
from app.schema.canonical import assert_canonical
from app.schema.contract import DS, SERIES_ID, Y
from app.schema.validation import ValidationReport

DEFAULT_MAX_SERIES = 150
DEFAULT_MAX_PERIODS = 120


@dataclass(slots=True)
class CoverageRow:
    series_id: str
    observations: int
    gaps: int
    zeros: int
    status: str
    route: str
    values: list[float | None] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "observations": self.observations,
            "gaps": self.gaps,
            "zeros": self.zeros,
            "status": self.status,
            "route": self.route,
            "values": list(self.values),
        }


@dataclass(slots=True)
class CoverageMatrix:
    frequency: ForecastFrequency
    periods: list[date] = field(default_factory=list)
    rows: list[CoverageRow] = field(default_factory=list)
    series_total: int = 0
    periods_total: int = 0
    required_history: int = 0

    @property
    def series_truncated(self) -> bool:
        return len(self.rows) < self.series_total

    @property
    def periods_truncated(self) -> bool:
        return len(self.periods) < self.periods_total

    def as_dict(self) -> dict[str, object]:
        return {
            "frequency": self.frequency.value,
            "periods": [period.isoformat() for period in self.periods],
            "rows": [row.as_dict() for row in self.rows],
            "series_total": self.series_total,
            "series_shown": len(self.rows),
            "periods_total": self.periods_total,
            "required_history": self.required_history,
            "series_truncated": self.series_truncated,
            "periods_truncated": self.periods_truncated,
        }


def coverage_matrix(
    frame: pl.DataFrame,
    report: ValidationReport,
    *,
    max_series: int = DEFAULT_MAX_SERIES,
    max_periods: int = DEFAULT_MAX_PERIODS,
) -> CoverageMatrix:
    """A series-by-period grid of what the file actually holds.

    Built over the calendar the frequency implies rather than over the periods
    present, so a month nobody reported is a column with a hole in it instead
    of a column that silently does not exist.
    """
    assert_canonical(frame)

    matrix = CoverageMatrix(
        frequency=report.frequency,
        required_history=report.required_history,
        series_total=len(report.series),
    )
    if frame.height == 0 or not report.series:
        return matrix

    span = expected_periods(frame[DS].min(), frame[DS].max(), report.frequency)  # type: ignore[arg-type]
    matrix.periods_total = len(span)
    matrix.periods = span[-max(1, max_periods) :]

    index = {period: position for position, period in enumerate(matrix.periods)}
    width = len(matrix.periods)
    routes = report.by_id

    rows: list[CoverageRow] = []
    for (series_id,), group in frame.group_by([SERIES_ID], maintain_order=True):
        values: list[float | None] = [None] * width
        for period, value in zip(group[DS].to_list(), group[Y].to_list(), strict=True):
            position = index.get(period)
            if position is not None:
                values[position] = float(value)

        present = [value for value in values if value is not None]
        checked = routes.get(str(series_id))
        rows.append(
            CoverageRow(
                series_id=str(series_id),
                observations=len(present),
                gaps=width - len(present),
                zeros=sum(1 for value in present if value == 0.0),
                status=checked.status if checked else "ok",
                route=checked.route if checked else "model",
                values=values,
            )
        )

    # When there are more series than the grid can carry, the patchiest are the
    # ones worth looking at — a page of complete series says nothing. They are
    # then put back into first-period order, so ragged starts still read as a
    # staircase rather than as noise.
    if len(rows) > max_series:
        rows.sort(key=lambda row: (-row.gaps, row.series_id))
        rows = rows[:max_series]

    rows.sort(key=lambda row: (_first_period(row), row.series_id))
    matrix.rows = rows
    return matrix


def _first_period(row: CoverageRow) -> int:
    return next(
        (index for index, value in enumerate(row.values) if value is not None), len(row.values)
    )
