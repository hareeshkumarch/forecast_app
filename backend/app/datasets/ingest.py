from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from app.core.config import settings
from app.core.errors import PayloadTooLargeError, UnsupportedFileError, ValidationError
from app.datasets.coercion import coerce_numeric

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


CSV_DELIMITERS = (",", ";", "\t", "|")

TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

MAX_PREAMBLE_LINES = 12


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in TEXT_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def _fields_outside_quotes(line: str, delimiter: str) -> int:
    count = 0
    quoted = False
    for character in line:
        if character == '"':
            quoted = not quoted
        elif character == delimiter and not quoted:
            count += 1
    return count


def _sniff_delimiter(sample: str) -> str:
    lines = [line for line in sample.splitlines() if line.strip()][:20]
    if not lines:
        return ","

    best, best_score, best_fields = ",", 0, 1
    for delimiter in CSV_DELIMITERS:
        counts = [
            fields for line in lines if (fields := _fields_outside_quotes(line, delimiter)) > 0
        ]
        if not counts:
            continue
        modal = max(set(counts), key=counts.count)
        agreeing = counts.count(modal)
        if (agreeing, modal) > (best_score, best_fields - 1):
            best, best_score, best_fields = delimiter, agreeing, modal + 1

    return best


def _header_offset(sample: str, delimiter: str) -> int:
    lines = sample.splitlines()[: MAX_PREAMBLE_LINES + 2]
    for index, line in enumerate(lines[:-1]):
        if not line.strip():
            continue
        # The first line that is divided into columns at all is the header.
        # Requiring the row under it to be the same width stepped over it
        # whenever that row came out wider — which is what an unquoted
        # thousands separator does — and the file then read one column short,
        # one row short, and headed by its own first record. A width that
        # disagrees means a ragged file, and there is a check that says so.
        if _fields_outside_quotes(line, delimiter) + 1 > 1:
            return index
    return 0


NULL_TOKENS = ["", "NA", "N/A", "null", "NULL", "#N/A", "-"]


def _read_csv_text(text: str, delimiter: str, skip: int) -> pl.DataFrame:
    return pl.read_csv(
        io.StringIO(text),
        separator=delimiter,
        skip_rows=skip,
        try_parse_dates=True,
        infer_schema_length=10_000,
        ignore_errors=False,
        truncate_ragged_lines=True,
        null_values=NULL_TOKENS,
    )


def _ragged_rows(text: str, delimiter: str, skip: int, width: int) -> int:
    # Split the way the reader splits. `splitlines` also breaks on a bare \r,
    # which the CSV reader treats as ordinary text, so the guard was counting
    # different rows than the parser was building and a genuinely ragged file
    # could pass it unmentioned.
    rows = [line.rstrip("\r") for line in text.split("\n")]
    lines = [line for line in rows[skip:] if line.strip()]
    return sum(1 for line in lines[1:] if _fields_outside_quotes(line, delimiter) + 1 > width)


SHEET_PROBE_ROWS = 40


def _read_excel(path: Path) -> pl.DataFrame:
    try:
        sheets = pl.read_excel(path, sheet_id=0)
    except Exception:
        return pl.read_excel(path)

    if isinstance(sheets, pl.DataFrame):
        return sheets
    if not sheets:
        raise ValidationError("The workbook has no sheets to read.")

    def score(frame: pl.DataFrame) -> tuple[int, int]:
        probe = frame.head(SHEET_PROBE_ROWS)
        filled = sum(
            int(probe[name].drop_nulls().len() > 0) for name in probe.columns if probe.height
        )
        return filled, frame.height

    ranked = sorted(sheets.items(), key=lambda item: score(item[1]), reverse=True)
    best = ranked[0][1]
    if best.height == 0:
        raise ValidationError("Every sheet in this workbook is empty.")
    return best


def _fill_merged_cells(frame: pl.DataFrame) -> pl.DataFrame:
    label_columns = [
        name
        for name in frame.columns
        if frame[name].dtype == pl.Utf8
        and 0 < frame[name].null_count() < frame.height
        and frame[name].drop_nulls().len() < frame.height * MERGED_LABEL_SHARE
    ]
    if not label_columns:
        return frame
    return frame.with_columns([pl.col(name).forward_fill() for name in label_columns])


MERGED_LABEL_SHARE = 0.5


def read_tabular(path: Path, suffix: str) -> pl.DataFrame:
    ragged = 0
    delimiter = ","
    try:
        if suffix in EXCEL_SUFFIXES:
            _assert_readable_excel(path)
            frame = _fill_merged_cells(_read_excel(path))
        else:
            text, _encoding = _decode(path.read_bytes())
            sample = "\n".join(text.splitlines()[:50])
            delimiter = "\t" if suffix == ".tsv" else _sniff_delimiter(sample)
            skip = _header_offset(sample, delimiter)
            frame = _read_csv_text(text, delimiter, skip)
            ragged = _ragged_rows(text, delimiter, skip, frame.width)
    except (ValidationError, UnsupportedFileError):
        raise
    except Exception as exc:
        raise ValidationError(
            f"The file couldn't be parsed: {type(exc).__name__}. "
            "Check that it has a single header row and consistent column counts."
        ) from exc

    if ragged:
        raise ValidationError(
            f"{ragged} row(s) hold more values than the header has columns, so reading the "
            "file would drop whatever sits past the last column. Check for an unquoted "
            f"'{delimiter}' inside a value, or a header that is missing a column.",
            detail={"ragged_rows": ragged, "columns": frame.width},
        )

    if frame.height == 0:
        raise ValidationError(
            "The file parsed successfully but contains no data rows — only headers."
        )

    if frame.width == 0:
        raise ValidationError("No columns were found in the file.")

    return _coerce_formatted_numbers(_clean_headers(_drop_empty_rows(frame)))


def _drop_empty_rows(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.height == 0:
        return frame
    keep = pl.any_horizontal(pl.all().is_not_null())
    trimmed = frame.filter(keep)
    return trimmed if trimmed.height else frame


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


def _coerce_formatted_numbers(frame: pl.DataFrame) -> pl.DataFrame:
    converted: list[pl.Series] = []

    for name in frame.columns:
        column = frame[name]
        if column.dtype != pl.Utf8:
            continue
        parsed = coerce_numeric(column)
        if parsed is not None:
            converted.append(parsed.values.rename(name))

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
