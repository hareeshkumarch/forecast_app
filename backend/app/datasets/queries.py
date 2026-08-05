from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from app.core.errors import ValidationError
from app.models.enums import ForecastFrequency, MeasureAggregation

DATE_TRUNC_PART: dict[ForecastFrequency, str] = {
    ForecastFrequency.DAILY: "day",
    ForecastFrequency.WEEKLY: "week",
    ForecastFrequency.MONTHLY: "month",
    ForecastFrequency.QUARTERLY: "quarter",
}

assert set(DATE_TRUNC_PART) == set(ForecastFrequency), "every frequency needs a truncation part"

AGGREGATIONS: dict[MeasureAggregation, str] = {
    MeasureAggregation.SUM: "SUM",
    MeasureAggregation.MEAN: "AVG",
    MeasureAggregation.MEDIAN: "MEDIAN",
    MeasureAggregation.LAST: "LAST",
    MeasureAggregation.MIN: "MIN",
    MeasureAggregation.MAX: "MAX",
}


def _quote(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise ValidationError(f"Invalid column name: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ValidationError(f"Expected a date from the time column, got {type(value).__name__}.")


@contextmanager
def connect() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(database=":memory:")
    try:
        yield connection
    finally:
        connection.close()


@dataclass(slots=True)
class AggregatedSeries:
    periods: list[date]
    values: list[float]
    weights: list[float] | None = None
    row_counts: list[int] = field(default_factory=list)
    rows_scanned: int = 0
    rows_usable: int = 0
    duplicate_rows: int = 0


def _source(parquet_path: Path) -> str:
    return f"read_parquet('{Path(parquet_path).as_posix()}')"


def aggregate_series(
    parquet_path: Path,
    time_column: str,
    target_column: str,
    frequency: ForecastFrequency,
    *,
    weight_column: str | None = None,
    start: date | None = None,
    end: date | None = None,
    aggregation: MeasureAggregation = MeasureAggregation.SUM,
) -> AggregatedSeries:
    part = DATE_TRUNC_PART[frequency]
    reducer = AGGREGATIONS[aggregation]
    time_sql = _quote(time_column)
    target_sql = _quote(target_column)

    select_weight = (
        f", SUM(TRY_CAST({_quote(weight_column)} AS DOUBLE)) AS w" if weight_column else ""
    )

    where = [
        f"TRY_CAST({time_sql} AS DATE) IS NOT NULL",
        f"TRY_CAST({target_sql} AS DOUBLE) IS NOT NULL",
    ]
    params: list[Any] = []
    if start is not None:
        where.append(f"TRY_CAST({time_sql} AS DATE) >= ?")
        params.append(start)
    if end is not None:
        where.append(f"TRY_CAST({time_sql} AS DATE) <= ?")
        params.append(end)

    order_for_last = f" ORDER BY TRY_CAST({time_sql} AS DATE)" if reducer == "LAST" else ""

    sql = f"""
        SELECT
            date_trunc('{part}', TRY_CAST({time_sql} AS DATE)) AS period,
            {reducer}(TRY_CAST({target_sql} AS DOUBLE){order_for_last}) AS value,
            COUNT(*) AS row_count
            {select_weight}
        FROM {_source(parquet_path)}
        WHERE {" AND ".join(where)}
        GROUP BY period
        ORDER BY period
    """

    scan_sql = f"""
        SELECT
            COUNT(*) AS scanned,
            COUNT(*) FILTER (
                WHERE TRY_CAST({time_sql} AS DATE) IS NOT NULL
                  AND TRY_CAST({target_sql} AS DOUBLE) IS NOT NULL
            ) AS usable
        FROM {_source(parquet_path)}
    """

    with connect() as connection:
        rows = connection.execute(sql, params).fetchall()
        scan = connection.execute(scan_sql).fetchone()

    scanned, usable = scan if scan else (0, 0)

    if not rows:
        raise ValidationError(
            f"No rows remain after parsing '{time_column}' as dates and "
            f"'{target_column}' as numbers. Check the column selection."
        )

    periods = [_as_date(row[0]) for row in rows]
    values = [float(row[1]) for row in rows]
    row_counts = [int(row[2]) for row in rows]
    weights = [float(row[3] or 0.0) for row in rows] if weight_column else None

    return AggregatedSeries(
        periods=periods,
        values=values,
        weights=weights,
        row_counts=row_counts,
        rows_scanned=int(scanned or 0),
        rows_usable=int(usable or 0),
        duplicate_rows=max(sum(row_counts) - len(row_counts), 0),
    )


@dataclass(slots=True)
class SegmentTotals:
    label: str
    current_total: float
    prior_total: float | None
    series: list[float]
    # The segment's whole history on the shared calendar, so it can be
    # forecast in its own right rather than split off the top line.
    periods: list[date] = field(default_factory=list)
    values: list[float] = field(default_factory=list)


def aggregate_segments(
    parquet_path: Path,
    time_column: str,
    target_column: str,
    segment_column: str,
    frequency: ForecastFrequency,
    *,
    window_periods: int = 12,
    max_segments: int = 12,
    start: date | None = None,
    end: date | None = None,
) -> list[SegmentTotals]:
    part = DATE_TRUNC_PART[frequency]
    time_sql = _quote(time_column)
    target_sql = _quote(target_column)
    segment_sql = _quote(segment_column)

    where = [
        f"TRY_CAST({time_sql} AS DATE) IS NOT NULL",
        f"TRY_CAST({target_sql} AS DOUBLE) IS NOT NULL",
        f"{segment_sql} IS NOT NULL",
    ]
    params: list[Any] = []
    if start is not None:
        where.append(f"TRY_CAST({time_sql} AS DATE) >= ?")
        params.append(start)
    if end is not None:
        where.append(f"TRY_CAST({time_sql} AS DATE) <= ?")
        params.append(end)

    sql = f"""
        SELECT
            CAST({segment_sql} AS VARCHAR) AS label,
            date_trunc('{part}', TRY_CAST({time_sql} AS DATE)) AS period,
            SUM(TRY_CAST({target_sql} AS DOUBLE)) AS value
        FROM {_source(parquet_path)}
        WHERE {" AND ".join(where)}
        GROUP BY label, period
        ORDER BY label, period
    """

    with connect() as connection:
        rows = connection.execute(sql, params).fetchall()

    if not rows:
        return []

    by_label: dict[str, list[tuple[date, float]]] = {}
    for label, period, value in rows:
        by_label.setdefault(str(label), []).append((_as_date(period), float(value)))

    all_periods = sorted({period for series in by_label.values() for period, _ in series})
    current_window = set(all_periods[-window_periods:])
    prior_window = set(all_periods[-2 * window_periods : -window_periods])

    totals: list[SegmentTotals] = []
    for label, series in by_label.items():
        current = sum(value for period, value in series if period in current_window)
        prior = sum(value for period, value in series if period in prior_window)

        # Reindexed onto the shared calendar: a segment that sold nothing in a
        # period genuinely sold nothing, and leaving the hole would misalign
        # its seasonality against every other segment.
        observed = dict(series)
        values = [float(observed.get(period, 0.0)) for period in all_periods]

        totals.append(
            SegmentTotals(
                label=label,
                current_total=current,
                prior_total=prior if prior_window else None,
                series=[value for period, value in series if period in current_window],
                periods=list(all_periods),
                values=values,
            )
        )

    totals.sort(key=lambda t: t.current_total, reverse=True)

    if len(totals) > max_segments:
        head, tail = totals[: max_segments - 1], totals[max_segments - 1 :]
        # The tail is pooled rather than dropped, and it is pooled as a series
        # so it can be forecast like any other segment.
        pooled = [sum(values) for values in zip(*(t.values for t in tail), strict=True)]
        others = SegmentTotals(
            label="Others",
            current_total=sum(t.current_total for t in tail),
            prior_total=(
                sum(t.prior_total or 0.0 for t in tail)
                if any(t.prior_total is not None for t in tail)
                else None
            ),
            series=[sum(window) for window in zip(*(t.series for t in tail), strict=False)],
            periods=list(all_periods),
            values=pooled,
        )
        totals = [*head, others]

    return totals


def column_names(parquet_path: Path) -> list[str]:
    with connect() as connection:
        cursor = connection.execute(f"SELECT * FROM {_source(parquet_path)} LIMIT 0")
        return [str(description[0]) for description in cursor.description or []]


@dataclass(slots=True)
class GroupedSeries:
    """One combination of the grouping columns, on the run's shared calendar."""

    key: dict[str, str]
    label: str
    periods: list[date]
    values: list[float]
    current_total: float
    prior_total: float | None
    pooled_from: int = 0


DEFAULT_MAX_SERIES = 500
SERIES_LABEL_SEPARATOR = " · "


def aggregate_grouped(
    parquet_path: Path,
    time_column: str,
    target_column: str,
    group_columns: list[str],
    frequency: ForecastFrequency,
    *,
    window_periods: int = 12,
    max_series: int = DEFAULT_MAX_SERIES,
    start: date | None = None,
    end: date | None = None,
    aggregation: MeasureAggregation = MeasureAggregation.SUM,
) -> list[GroupedSeries]:
    """
    A series per combination of `group_columns`, reindexed onto one calendar.

    Every series shares the same periods so their seasonality lines up and they
    can be summed at any level. A combination that recorded nothing in a period
    genuinely recorded nothing, so the hole is a zero rather than a gap.

    Combinations beyond `max_series` are pooled into one `Others` series rather
    than dropped: the total has to stay whole.
    """
    if not group_columns:
        raise ValidationError("Grouped aggregation needs at least one grouping column.")

    part = DATE_TRUNC_PART[frequency]
    reducer = AGGREGATIONS[aggregation]
    time_sql = _quote(time_column)
    target_sql = _quote(target_column)
    group_sql = [_quote(column) for column in group_columns]

    where = [
        f"TRY_CAST({time_sql} AS DATE) IS NOT NULL",
        f"TRY_CAST({target_sql} AS DOUBLE) IS NOT NULL",
    ]
    params: list[Any] = []
    if start is not None:
        where.append(f"TRY_CAST({time_sql} AS DATE) >= ?")
        params.append(start)
    if end is not None:
        where.append(f"TRY_CAST({time_sql} AS DATE) <= ?")
        params.append(end)

    order_for_last = f" ORDER BY TRY_CAST({time_sql} AS DATE)" if reducer == "LAST" else ""
    select_keys = ", ".join(
        f"COALESCE(CAST({column} AS VARCHAR), '(none)') AS k{index}"
        for index, column in enumerate(group_sql)
    )
    group_keys = ", ".join(f"k{index}" for index in range(len(group_sql)))

    sql = f"""
        SELECT
            {select_keys},
            date_trunc('{part}', TRY_CAST({time_sql} AS DATE)) AS period,
            {reducer}(TRY_CAST({target_sql} AS DOUBLE){order_for_last}) AS value
        FROM {_source(parquet_path)}
        WHERE {" AND ".join(where)}
        GROUP BY {group_keys}, period
        ORDER BY {group_keys}, period
    """

    with connect() as connection:
        rows = connection.execute(sql, params).fetchall()

    if not rows:
        return []

    depth = len(group_columns)
    observed: dict[tuple[str, ...], dict[date, float]] = {}
    for row in rows:
        key = tuple(str(value) for value in row[:depth])
        observed.setdefault(key, {})[_as_date(row[depth])] = float(row[depth + 1] or 0.0)

    calendar = sorted({period for series in observed.values() for period in series})
    current_window = calendar[-window_periods:]
    prior_window = calendar[-2 * window_periods : -window_periods]

    def build(key: tuple[str, ...], by_period: dict[date, float]) -> GroupedSeries:
        values = [by_period.get(period, 0.0) for period in calendar]
        return GroupedSeries(
            key=dict(zip(group_columns, key, strict=True)),
            label=SERIES_LABEL_SEPARATOR.join(key),
            periods=list(calendar),
            values=values,
            current_total=sum(by_period.get(period, 0.0) for period in current_window),
            prior_total=(
                sum(by_period.get(period, 0.0) for period in prior_window) if prior_window else None
            ),
        )

    series = [build(key, by_period) for key, by_period in observed.items()]
    series.sort(key=lambda s: s.current_total, reverse=True)

    if len(series) > max_series:
        head, tail = series[: max_series - 1], series[max_series - 1 :]
        pooled = [sum(column) for column in zip(*(s.values for s in tail), strict=True)]
        head.append(
            GroupedSeries(
                key=dict.fromkeys(group_columns, "(others)"),
                label="Others",
                periods=list(calendar),
                values=pooled,
                current_total=sum(s.current_total for s in tail),
                prior_total=(
                    sum(s.prior_total or 0.0 for s in tail)
                    if any(s.prior_total is not None for s in tail)
                    else None
                ),
                pooled_from=len(tail),
            )
        )
        series = head

    return series
