from __future__ import annotations

import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from app.core.config import settings
from app.core.errors import PayloadTooLargeError, UnsupportedFileError, ValidationError

CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
SUPPORTED_SUFFIXES = CSV_SUFFIXES | EXCEL_SUFFIXES


LEGACY_EXCEL_SUFFIXES = {".xls"}


OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@dataclass(slots=True)
class IngestResult:
    frame: pl.DataFrame
    raw_path: Path
    file_size_bytes: int
    original_filename: str


def validate_upload(filename: str, size_bytes: int) -> str:
    if not filename or "." not in filename:
        raise UnsupportedFileError(
            "The file has no extension, so its format can't be determined. "
            "Upload a .csv or .xlsx file."
        )

    suffix = Path(filename).suffix.lower()

    if suffix in LEGACY_EXCEL_SUFFIXES:
        raise UnsupportedFileError(
            "Legacy .xls files aren't supported. Open the file in Excel and "
            "re-save it as .xlsx, then upload again."
        )

    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise UnsupportedFileError(
            f"'{suffix}' files aren't supported. Supported formats: {supported}."
        )

    if size_bytes <= 0:
        raise ValidationError("The uploaded file is empty (0 bytes).")

    if size_bytes > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes / (1024 * 1024)
        actual_mb = size_bytes / (1024 * 1024)
        raise PayloadTooLargeError(
            f"The file is {actual_mb:.1f} MB, which exceeds the {limit_mb:.0f} MB limit. "
            "Filter or aggregate the data before uploading.",
            detail={"size_bytes": size_bytes, "limit_bytes": settings.max_upload_bytes},
        )

    return suffix


def _assert_readable_excel(path: Path) -> None:
    with path.open("rb") as handle:
        header = handle.read(8)

    if header == OLE2_MAGIC:
        raise ValidationError(
            "This workbook appears to be password-protected or saved in the legacy "
            "Excel format. Remove the password, save it as .xlsx, and try again."
        )

    if not zipfile.is_zipfile(path):
        raise ValidationError(
            "The file has an .xlsx extension but isn't a valid Excel workbook. "
            "It may have been renamed or truncated during upload."
        )


def read_tabular(path: Path, suffix: str) -> pl.DataFrame:
    try:
        if suffix in EXCEL_SUFFIXES:
            _assert_readable_excel(path)
            frame = pl.read_excel(path)
        else:
            separator = "\t" if suffix == ".tsv" else ","
            frame = pl.read_csv(
                path,
                separator=separator,
                try_parse_dates=True,
                infer_schema_length=10_000,
                ignore_errors=False,
                null_values=["", "NA", "N/A", "null", "NULL", "#N/A", "-"],
            )
    except (ValidationError, UnsupportedFileError):
        raise
    except Exception as exc:
        raise ValidationError(
            f"The file couldn't be parsed: {type(exc).__name__}. "
            "Check that it has a single header row and consistent column counts."
        ) from exc

    if frame.height == 0:
        raise ValidationError(
            "The file parsed successfully but contains no data rows — only headers."
        )

    if frame.width == 0:
        raise ValidationError("No columns were found in the file.")

    return _coerce_formatted_numbers(_clean_headers(frame))


def _clean_headers(frame: pl.DataFrame) -> pl.DataFrame:
    seen: dict[str, int] = {}
    renames: dict[str, str] = {}

    for original in frame.columns:
        cleaned = original.strip() or "column"
        if cleaned in seen:
            seen[cleaned] += 1
            cleaned = f"{cleaned}_{seen[cleaned]}"
        else:
            seen[cleaned] = 0
        if cleaned != original:
            renames[original] = cleaned

    return frame.rename(renames) if renames else frame


def _currency_symbols() -> str:
    """
    Every character Unicode calls a currency symbol, escaped for a regex class.

    Derived rather than listed: a hand-written set of $, €, £ silently fails
    the first customer whose exports are in ₹ or ₦, and there is no reason to
    make them find that out.
    """
    symbols = (chr(code) for code in range(0xFFFF) if unicodedata.category(chr(code)) == "Sc")
    return "".join(re.escape(symbol) for symbol in symbols)


#: Decoration a spreadsheet wraps a number in: thousands separators, spaces
#: (including the non-breaking kind Excel emits), a percent sign, a currency
#: symbol. Nothing else — stripping letters as well turned "SKU-0093" into the
#: number -93 and "W1" into 1, destroying the identifier and hiding the column
#: from the grain it should have been offered as.
NUMERIC_DECORATION_PATTERN = rf"[\s,_%{_currency_symbols()}]"
NUMERIC_COERCION_RATIO = 0.9
NUMERIC_SAMPLE_ROWS = 500


def _coerce_formatted_numbers(frame: pl.DataFrame) -> pl.DataFrame:
    """
    Spreadsheet exports carry measures as text: "$1,200", "1 350", "(450)",
    "12.5%". Left as strings they are never offered as a forecast target, so a
    column that is overwhelmingly numeric once the decoration is stripped is
    converted here, before anything downstream sees it.
    """
    converted: list[pl.Expr] = []

    for name, dtype in zip(frame.columns, frame.dtypes, strict=True):
        if dtype != pl.Utf8:
            continue

        column = frame[name].drop_nulls()
        if column.len() == 0:
            continue

        sample = column.head(NUMERIC_SAMPLE_ROWS)
        text = sample.str.strip_chars()
        # Accounting negatives: (450) means -450.
        text = text.str.replace_all(r"^\((.*)\)$", "-${1}")
        stripped = text.str.replace_all(NUMERIC_DECORATION_PATTERN, "")

        parsed = stripped.cast(pl.Float64, strict=False)
        usable = parsed.drop_nulls().len()
        if usable == 0 or usable < NUMERIC_COERCION_RATIO * sample.len():
            continue

        # A bare year column is numeric but is a label, not a measure.
        if stripped.str.len_chars().max() == 4 and parsed.min() is not None:
            low, high = float(parsed.min()), float(parsed.max())  # type: ignore[arg-type]
            if 1800 <= low <= 2200 and 1800 <= high <= 2200:
                continue

        converted.append(
            pl.col(name)
            .str.strip_chars()
            .str.replace_all(r"^\((.*)\)$", "-${1}")
            .str.replace_all(NUMERIC_DECORATION_PATTERN, "")
            .cast(pl.Float64, strict=False)
            .alias(name)
        )

    return frame.with_columns(converted) if converted else frame


def persist_upload(content: bytes, filename: str, dataset_id: str) -> IngestResult:
    suffix = validate_upload(filename, len(content))
    settings.ensure_directories()

    raw_path = settings.uploads_dir / f"{dataset_id}{suffix}"
    raw_path.write_bytes(content)

    try:
        frame = read_tabular(raw_path, suffix)
    except Exception:
        raw_path.unlink(missing_ok=True)
        raise

    return IngestResult(
        frame=frame,
        raw_path=raw_path,
        file_size_bytes=len(content),
        original_filename=filename,
    )


def write_parquet(frame: pl.DataFrame, dataset_id: str) -> Path:
    settings.ensure_directories()
    path = settings.parquet_dir / f"{dataset_id}.parquet"
    frame.write_parquet(path, compression="zstd")
    return path
