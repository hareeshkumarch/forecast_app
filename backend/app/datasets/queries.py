from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from app.core.errors import ValidationError
from app.forecasting.frequency import comparison_window, periods_per_year
from app.models.enums import ForecastFrequency, MeasureAggregation

POOLED_LABEL = "Others"
POOLED_KEY = "(others)"

MISSING_KEY = "(none)"

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

#: A period a series has no row for. Not zero — a SKU nobody reported this
#: month and a SKU that sold nothing this month are different facts, and only
#: the run's gap-fill setting decides which one to treat it as. Writing the
#: zero here made that decision for every grouped series, whatever was asked
#: for, and made it invisible.
NOT_REPORTED = float("nan")


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


@contextmanager
def _using(borrowed: duckdb.DuckDBPyConnection | None) -> Iterator[duckdb.DuckDBPyConnection]:
    if borrowed is not None:
        yield borrowed
        return
    with connect() as opened:
        yield opened


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


def aggregate_candidate_drivers(
    parquet_path: Path,
    time_column: str,
    columns: list[str],
    frequency: ForecastFrequency,
    periods: list[date],
    *,
    aggregation: MeasureAggregation = MeasureAggregation.SUM,
    per_column: dict[str, MeasureAggregation] | None = None,
) -> dict[str, list[float]]:
    """Bring each driver to the run's calendar, reduced by what it *is*.

    A driver took the target's aggregation, which is a statement about the
    target and not about the driver. Sum a price, an index, a temperature or a
    conversion rate across the rows in a month and the number that comes out
    grows with the row count and means nothing — and the correlation search
    that follows it is then reading traffic volume, not the driver.
    """
    if not columns or not periods:
        return {}

    part = DATE_TRUNC_PART[frequency]
    chosen = per_column or {}
    time_sql = _quote(time_column)

    def projection(index: int, name: str) -> str:
        reducer = AGGREGATIONS[chosen.get(name, aggregation)]
        order = f" ORDER BY TRY_CAST({time_sql} AS DATE)" if reducer == "LAST" else ""
        return f"{reducer}(TRY_CAST({_quote(name)} AS DOUBLE){order}) AS c{index}"

    projections = ", ".join(projection(index, name) for index, name in enumerate(columns))

    sql = f"""
        SELECT date_trunc('{part}', TRY_CAST({time_sql} AS DATE)) AS period, {projections}
        FROM {_source(parquet_path)}
        WHERE TRY_CAST({time_sql} AS DATE) IS NOT NULL
        GROUP BY period
        ORDER BY period
    """

    with connect() as connection:
        rows = connection.execute(sql).fetchall()

    by_period = {_as_date(row[0]): row[1:] for row in rows}

    out: dict[str, list[float]] = {}
    for index, name in enumerate(columns):
        series = [by_period.get(period, (None,) * len(columns))[index] for period in periods]
        present = sum(1 for value in series if value is not None)
        if present < len(periods) // 2:
            continue
        out[name] = [float("nan") if value is None else float(value) for value in series]

    return out


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
    periods: list[date] = field(default_factory=list)
    values: list[float] = field(default_factory=list)


def aggregate_segments(
    parquet_path: Path,
    time_column: str,
    target_column: str,
    segment_column: str,
    frequency: ForecastFrequency,
    *,
    window_periods: int | None = None,
    max_segments: int = 12,
    start: date | None = None,
    end: date | None = None,
    aggregation: MeasureAggregation = MeasureAggregation.SUM,
) -> list[SegmentTotals]:
    part = DATE_TRUNC_PART[frequency]
    reducer = AGGREGATIONS[aggregation]
    time_sql = _quote(time_column)
    target_sql = _quote(target_column)
    segment_sql = _quote(segment_column)
    order_for_last = f" ORDER BY TRY_CAST({time_sql} AS DATE)" if reducer == "LAST" else ""

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
            {reducer}(TRY_CAST({target_sql} AS DOUBLE){order_for_last}) AS value
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
    window = window_periods or comparison_window(frequency, len(all_periods))
    current_window = set(all_periods[-window:])
    prior_window = set(all_periods[-2 * window : -window])

    totals: list[SegmentTotals] = []
    for label, series in by_label.items():
        current = sum(value for period, value in series if period in current_window)
        prior = sum(value for period, value in series if period in prior_window)

        observed = dict(series)
        values = [float(observed.get(period, NOT_REPORTED)) for period in all_periods]

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
        pooled = [sum(values) for values in zip(*(t.values for t in tail), strict=True)]
        others = SegmentTotals(
            label=POOLED_LABEL,
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


def column_names(
    parquet_path: Path,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> list[str]:
    with _using(connection) as db:
        cursor = db.execute(f"SELECT * FROM {_source(parquet_path)} LIMIT 0")
        return [str(description[0]) for description in cursor.description or []]


@dataclass(slots=True)
class ObservedWindow:
    covered_through: date | None
    totals: dict[date, float]
    by_key: dict[tuple[str, ...], dict[date, float]]


def observed_window(
    parquet_path: Path,
    time_column: str,
    target_column: str,
    frequency: ForecastFrequency,
    *,
    start: date,
    end: date,
    group_columns: list[str] | None = None,
    aggregation: MeasureAggregation = MeasureAggregation.SUM,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> ObservedWindow:
    part = DATE_TRUNC_PART[frequency]
    reducer = AGGREGATIONS[aggregation]
    time_sql = _quote(time_column)
    target_sql = _quote(target_column)
    order_for_last = f" ORDER BY TRY_CAST({time_sql} AS DATE)" if reducer == "LAST" else ""

    where = (
        f"TRY_CAST({time_sql} AS DATE) IS NOT NULL "
        f"AND TRY_CAST({target_sql} AS DOUBLE) IS NOT NULL "
        f"AND TRY_CAST({time_sql} AS DATE) BETWEEN ? AND ?"
    )
    window: list[Any] = [start, end]

    totals_sql = f"""
        SELECT
            date_trunc('{part}', TRY_CAST({time_sql} AS DATE)) AS period,
            {reducer}(TRY_CAST({target_sql} AS DOUBLE){order_for_last}) AS value
        FROM {_source(parquet_path)}
        WHERE {where}
        GROUP BY period
        ORDER BY period
    """

    reach_sql = f"""
        SELECT MAX(TRY_CAST({time_sql} AS DATE))
        FROM {_source(parquet_path)}
        WHERE TRY_CAST({time_sql} AS DATE) IS NOT NULL
    """

    by_key: dict[tuple[str, ...], dict[date, float]] = {}
    with _using(connection) as db:
        totals = {
            _as_date(row[0]): float(row[1] or 0.0)
            for row in db.execute(totals_sql, list(window)).fetchall()
        }
        reach = db.execute(reach_sql).fetchone()

        if group_columns:
            depth = len(group_columns)
            select_keys = ", ".join(
                f"COALESCE(CAST({_quote(column)} AS VARCHAR), '{MISSING_KEY}') AS k{index}"
                for index, column in enumerate(group_columns)
            )
            group_keys = ", ".join(f"k{index}" for index in range(depth))
            keyed_sql = f"""
                SELECT
                    {select_keys},
                    date_trunc('{part}', TRY_CAST({time_sql} AS DATE)) AS period,
                    {reducer}(TRY_CAST({target_sql} AS DOUBLE){order_for_last}) AS value
                FROM {_source(parquet_path)}
                WHERE {where}
                GROUP BY {group_keys}, period
            """
            for row in db.execute(keyed_sql, list(window)).fetchall():
                key = tuple(str(value) for value in row[:depth])
                by_key.setdefault(key, {})[_as_date(row[depth])] = float(row[depth + 1] or 0.0)

    covered = reach[0] if reach else None
    return ObservedWindow(
        covered_through=_as_date(covered) if covered is not None else None,
        totals=totals,
        by_key=by_key,
    )


@dataclass(slots=True)
class GroupedSeries:
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
    window_periods: int | None = None,
    max_series: int = DEFAULT_MAX_SERIES,
    start: date | None = None,
    end: date | None = None,
    aggregation: MeasureAggregation = MeasureAggregation.SUM,
) -> list[GroupedSeries]:
    if not group_columns:
        raise ValidationError("Grouped aggregation needs at least one grouping column.")

    max_series = max(1, min(int(max_series), DEFAULT_MAX_SERIES))
    requested_window = max(1, int(window_periods)) if window_periods else None

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
        f"COALESCE(CAST({column} AS VARCHAR), '{MISSING_KEY}') AS k{index}"
        for index, column in enumerate(group_sql)
    )
    group_keys = ", ".join(f"k{index}" for index in range(len(group_sql)))
    qualified_keys = ", ".join(f"values_by_period.k{index}" for index in range(len(group_sql)))
    rank_order = ", ".join(f"k{index}" for index in range(len(group_sql)))
    keep_count = max_series - 1
    pooled_condition = (
        f"ranked_keys.series_total > {max_series} " f"AND ranked_keys.series_rank > {keep_count}"
    )
    bounded_keys = ",\n            ".join(
        f"CASE WHEN {pooled_condition} THEN '{POOLED_KEY}' "
        f"ELSE values_by_period.k{index} END AS k{index}"
        for index in range(len(group_sql))
    )

    if requested_window:
        ranking_window = str(requested_window)
    else:
        year = periods_per_year(frequency)
        ranking_window = (
            f"CASE WHEN periods.period_count >= {2 * year} THEN {year} "
            "ELSE GREATEST(1, CAST(FLOOR(periods.period_count / 2) AS INTEGER)) END"
        )

    sql = f"""
        WITH values_by_period AS (
            SELECT
                {select_keys},
                date_trunc('{part}', TRY_CAST({time_sql} AS DATE)) AS period,
                {reducer}(TRY_CAST({target_sql} AS DOUBLE){order_for_last}) AS value
            FROM {_source(parquet_path)}
            WHERE {" AND ".join(where)}
            GROUP BY {group_keys}, period
        ),
        periods AS (
            SELECT
                period,
                ROW_NUMBER() OVER (ORDER BY period DESC) AS recent_rank,
                COUNT(*) OVER () AS period_count
            FROM (SELECT DISTINCT period FROM values_by_period)
        ),
        key_totals AS (
            SELECT
                {qualified_keys},
                SUM(
                    CASE WHEN periods.recent_rank <= {ranking_window}
                         THEN values_by_period.value ELSE 0 END
                ) AS current_total
            FROM values_by_period
            JOIN periods USING (period)
            GROUP BY {qualified_keys}
        ),
        ranked_keys AS (
            SELECT
                *,
                ROW_NUMBER() OVER (ORDER BY current_total DESC, {rank_order}) AS series_rank,
                COUNT(*) OVER () AS series_total
            FROM key_totals
        ),
        bounded AS (
            SELECT
                {bounded_keys},
                values_by_period.period,
                values_by_period.value,
                ({pooled_condition}) AS pooled,
                CASE WHEN {pooled_condition}
                     THEN ranked_keys.series_total - {keep_count} ELSE 0 END AS pooled_from
            FROM values_by_period
            JOIN ranked_keys USING ({group_keys})
        )
        SELECT
            {group_keys},
            period,
            SUM(value) AS value,
            pooled,
            MAX(pooled_from) AS pooled_from
        FROM bounded
        GROUP BY {group_keys}, period, pooled
        ORDER BY pooled, {group_keys}, period
    """

    with connect() as connection:
        rows = connection.execute(sql, params).fetchall()

    if not rows:
        return []

    depth = len(group_columns)
    observed: dict[tuple[tuple[str, ...], bool], dict[date, float]] = {}
    pooled_counts: dict[tuple[tuple[str, ...], bool], int] = {}
    for row in rows:
        key = tuple(str(value) for value in row[:depth])
        pooled = bool(row[depth + 2])
        bucket = (key, pooled)
        observed.setdefault(bucket, {})[_as_date(row[depth])] = float(row[depth + 1] or 0.0)
        pooled_counts[bucket] = int(row[depth + 3] or 0)

    calendar = sorted({period for series in observed.values() for period in series})
    window = requested_window or comparison_window(frequency, len(calendar))
    current_window = calendar[-window:]
    prior_window = calendar[-2 * window : -window]

    def build(bucket: tuple[tuple[str, ...], bool], by_period: dict[date, float]) -> GroupedSeries:
        key, pooled = bucket
        values = [by_period.get(period, NOT_REPORTED) for period in calendar]
        return GroupedSeries(
            key=dict(zip(group_columns, key, strict=True)),
            label=POOLED_LABEL if pooled else SERIES_LABEL_SEPARATOR.join(key),
            periods=list(calendar),
            values=values,
            current_total=sum(by_period.get(period, 0.0) for period in current_window),
            prior_total=(
                sum(by_period.get(period, 0.0) for period in prior_window) if prior_window else None
            ),
            pooled_from=pooled_counts[bucket],
        )

    series = [build(bucket, by_period) for bucket, by_period in observed.items()]
    series.sort(key=lambda item: (item.pooled_from > 0, -item.current_total, item.label))

    return series
