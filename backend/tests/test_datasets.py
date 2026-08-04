from __future__ import annotations

import zipfile
from datetime import date

import polars as pl
import pytest

from app.core.errors import PayloadTooLargeError, UnsupportedFileError, ValidationError
from app.datasets.ingest import (
    _coerce_formatted_numbers,
    persist_upload,
    read_tabular,
    validate_upload,
    write_parquet,
)
from app.datasets.profiler import profile_frame
from app.datasets.queries import aggregate_segments, aggregate_series
from app.models.enums import ColumnKind, ColumnRole, ForecastFrequency


def sample_frame(months: int = 24) -> pl.DataFrame:
    rows = []
    for index in range(months):
        year, month = 2023 + index // 12, index % 12 + 1
        for region in ("North America", "Europe"):
            rows.append(
                {
                    "order_date": f"{year}-{month:02d}-01",
                    "region": region,
                    "revenue": 1000.0 + index * 10 + (100 if region == "Europe" else 0),
                    "units_sold": 20 + index,
                    "row_id": len(rows) + 1,
                }
            )
    return pl.DataFrame(rows)


@pytest.mark.parametrize(
    ("filename", "size", "exc", "fragment"),
    [
        ("data", 100, UnsupportedFileError, "no extension"),
        ("legacy.xls", 100, UnsupportedFileError, "re-save it as .xlsx"),
        ("report.pdf", 100, UnsupportedFileError, "aren't supported"),
        ("empty.csv", 0, ValidationError, "empty"),
        ("huge.csv", 21 * 1024 * 1024, PayloadTooLargeError, "exceeds"),
    ],
)
def test_upload_validation_messages_are_specific(
    filename: str, size: int, exc: type[Exception], fragment: str
) -> None:
    with pytest.raises(exc) as info:
        validate_upload(filename, size)
    assert fragment.lower() in str(info.value).lower()


def test_accepts_supported_extensions() -> None:
    for filename in ("a.csv", "b.tsv", "c.txt", "d.xlsx", "e.xlsm"):
        assert validate_upload(filename, 1024).startswith(".")


def test_headers_only_file_is_rejected(tmp_path) -> None:
    path = tmp_path / "h.csv"
    path.write_text("a,b,c\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="no data rows"):
        read_tabular(path, ".csv")


def test_password_protected_workbook_is_detected(tmp_path) -> None:
    path = tmp_path / "locked.xlsx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)

    with pytest.raises(ValidationError, match="password-protected"):
        read_tabular(path, ".xlsx")


def test_corrupt_xlsx_is_distinguished_from_encrypted(tmp_path) -> None:
    path = tmp_path / "fake.xlsx"
    path.write_bytes(b"this is definitely not a workbook")

    with pytest.raises(ValidationError, match="isn't a valid Excel workbook"):
        read_tabular(path, ".xlsx")


def test_real_xlsx_round_trips(tmp_path) -> None:
    try:
        import xlsxwriter  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        pytest.skip("xlsxwriter not installed")

    path = tmp_path / "real.xlsx"
    sample_frame(6).write_excel(path)

    assert zipfile.is_zipfile(path)
    frame = read_tabular(path, ".xlsx")
    assert frame.height == 12


def test_duplicate_headers_are_deduplicated(tmp_path) -> None:
    path = tmp_path / "dup.csv"
    path.write_text("date,rev,rev\n2024-01-01,5,6\n2024-02-01,7,8\n", encoding="utf-8")

    frame = read_tabular(path, ".csv")
    assert len(set(frame.columns)) == len(frame.columns)


def test_failed_upload_does_not_leave_a_file_behind() -> None:
    from app.core.config import settings

    before = set(settings.uploads_dir.glob("*")) if settings.uploads_dir.exists() else set()

    with pytest.raises(ValidationError):
        persist_upload(b"a,b\n", "headers-only.csv", "cleanup-test")

    after = set(settings.uploads_dir.glob("*")) if settings.uploads_dir.exists() else set()
    assert after == before


def test_profiler_detects_roles() -> None:
    profile = profile_frame(sample_frame())

    by_name = {column.name: column for column in profile.columns}
    assert by_name["order_date"].kind is ColumnKind.DATE
    assert by_name["order_date"].role is ColumnRole.TIME
    assert by_name["revenue"].role is ColumnRole.TARGET
    assert by_name["region"].role is ColumnRole.DIMENSION
    assert profile.detected_frequency is ForecastFrequency.MONTHLY


def test_profiler_rejects_id_columns_as_targets() -> None:
    profile = profile_frame(sample_frame())
    row_id = next(column for column in profile.columns if column.name == "row_id")

    assert row_id.is_target_candidate is False
    assert "identifier" in row_id.reason


def test_profiler_prefers_revenue_over_units_as_target() -> None:
    profile = profile_frame(sample_frame())
    by_name = {column.name: column for column in profile.columns}

    assert by_name["revenue"].target_score > by_name["units_sold"].target_score
    assert by_name["units_sold"].role is ColumnRole.WEIGHT


def test_profiler_reports_date_range_and_missing_counts() -> None:
    frame = sample_frame(12).with_columns(
        pl.when(pl.col("row_id") == 1).then(None).otherwise(pl.col("revenue")).alias("revenue")
    )
    profile = profile_frame(frame)

    assert profile.missing_value_count == 1
    assert profile.date_range_start == date(2023, 1, 1)
    assert profile.date_range_end == date(2023, 12, 1)


def test_profiler_warns_on_short_history() -> None:
    profile = profile_frame(sample_frame(2))
    assert any("rows" in warning for warning in profile.warnings)


def test_profiler_warns_when_no_date_column() -> None:
    frame = pl.DataFrame({"name": ["a", "b"], "amount": [1.0, 2.0]})
    profile = profile_frame(frame)

    assert any("date" in warning.lower() for warning in profile.warnings)


def test_aggregate_series_sums_onto_the_period_grid() -> None:
    frame = sample_frame(12)
    path = write_parquet(frame, "agg-test")

    series = aggregate_series(path, "order_date", "revenue", ForecastFrequency.MONTHLY)

    assert len(series.periods) == 12
    assert all(isinstance(period, date) for period in series.periods)

    assert series.values[0] == pytest.approx(1000.0 + 1100.0)


def test_aggregate_series_respects_the_date_filter() -> None:
    path = write_parquet(sample_frame(24), "agg-filter")

    filtered = aggregate_series(
        path,
        "order_date",
        "revenue",
        ForecastFrequency.MONTHLY,
        start=date(2024, 1, 1),
        end=date(2024, 6, 1),
    )
    assert len(filtered.periods) == 6


def test_aggregate_series_raises_when_nothing_parses() -> None:
    path = write_parquet(sample_frame(6), "agg-bad")

    with pytest.raises(ValidationError, match="No rows remain"):
        aggregate_series(path, "region", "revenue", ForecastFrequency.MONTHLY)


def test_aggregate_segments_computes_prior_window() -> None:
    path = write_parquet(sample_frame(24), "seg-test")

    segments = aggregate_segments(
        path, "order_date", "revenue", "region", ForecastFrequency.MONTHLY, window_periods=12
    )

    assert {segment.label for segment in segments} == {"North America", "Europe"}
    for segment in segments:
        assert segment.current_total > 0
        assert segment.prior_total is not None

        assert segment.current_total > segment.prior_total


def test_aggregate_segments_buckets_the_long_tail() -> None:
    rows = [
        {"d": f"2024-{month:02d}-01", "seg": f"S{index}", "v": 10.0}
        for month in range(1, 13)
        for index in range(20)
    ]
    path = write_parquet(pl.DataFrame(rows), "seg-tail")

    segments = aggregate_segments(path, "d", "v", "seg", ForecastFrequency.MONTHLY, max_segments=5)

    assert len(segments) == 5
    assert segments[-1].label == "Others"


def test_column_name_quoting_blocks_injection() -> None:
    frame = pl.DataFrame({'evil"; DROP TABLE x; --': [1, 2], "d": ["2024-01-01", "2024-02-01"]})
    path = write_parquet(frame, "inject-test")

    from app.datasets.queries import column_names

    names = column_names(path)
    assert 'evil"; DROP TABLE x; --' in names


def test_currency_and_thousands_separators_become_measures() -> None:
    csv = (
        "period,revenue,units,note\n"
        '2024-01-01,"$1,200.50",12,ok\n'
        '2024-02-01,"$1,350.00",15,ok\n'
        '2024-03-01,"$1,400.25",18,fine\n'
        '2024-04-01,"$1,510.75",21,ok\n'
    )
    frame = persist_upload(csv.encode(), "money.csv", "coerce-money").frame

    assert frame["revenue"].dtype == pl.Float64
    assert frame["revenue"][0] == pytest.approx(1200.50)
    assert frame["note"].dtype == pl.Utf8, "prose must stay prose"

    profile = profile_frame(frame)
    target = next(c.name for c in profile.columns if c.role is ColumnRole.TARGET)
    assert target in {"revenue", "units"}


def test_accounting_negatives_are_read_as_negative() -> None:
    csv = "period,amount\n2024-01-01,(450)\n2024-02-01,1200\n2024-03-01,(75)\n2024-04-01,900\n"
    frame = persist_upload(csv.encode(), "ledger.csv", "coerce-ledger").frame

    assert frame["amount"].to_list() == [-450.0, 1200.0, -75.0, 900.0]


def test_a_text_year_column_is_left_as_a_label() -> None:
    # Polars already types a bare integer column as Int64, so the guard only
    # ever sees a year that arrived as text — a trailing space is enough.
    frame = pl.DataFrame(
        {
            "period": ["2024-01-01", "2024-02-01", "2024-03-01"],
            "fiscal_year": ["2024 ", "2024 ", "2025 "],
            "revenue": ["$100", "$110", "$120"],
        }
    )

    coerced = _coerce_formatted_numbers(frame)

    assert coerced["fiscal_year"].dtype == pl.Utf8, "a year is a label, not a measure"
    assert coerced["revenue"].dtype == pl.Float64


def test_a_mostly_textual_column_is_not_coerced() -> None:
    csv = "period,label\n2024-01-01,north\n2024-02-01,south\n2024-03-01,12\n2024-04-01,east\n"
    frame = persist_upload(csv.encode(), "labels.csv", "coerce-labels").frame

    assert frame["label"].dtype == pl.Utf8
