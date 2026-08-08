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


#: Delimiters worth trying, in the order they are worth trying. A semicolon is
#: what Excel writes anywhere the comma is the decimal separator, which is most
#: of continental Europe — reading it as a comma file yields exactly one column
#: holding the whole line.
CSV_DELIMITERS = (",", ";", "\t", "|")

#: Text encodings, most likely first. UTF-8 covers almost everything; the rest
#: are what a Windows export from a non-English locale produces.
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

#: How far down the file to look for the real header. Exports often open with a
#: report title and a blank line before the column names.
MAX_PREAMBLE_LINES = 12


def _decode(raw: bytes) -> tuple[str, str]:
    """Decode a file, returning the text and the encoding that worked.

    Latin-1 accepts any byte sequence, so it is last and acts as the backstop:
    reaching it means the text may be wrong, but it will not be an exception.
    """
    for encoding in TEXT_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def _fields_outside_quotes(line: str, delimiter: str) -> int:
    """Count delimiters that actually separate fields.

    A quoted value is allowed to contain the delimiter — "Smith, John" is one
    field in a comma file — so counting raw characters makes the header look a
    column narrower than the rows beneath it.
    """
    count = 0
    quoted = False
    for character in line:
        if character == '"':
            quoted = not quoted
        elif character == delimiter and not quoted:
            count += 1
    return count


def _sniff_delimiter(sample: str) -> str:
    """The delimiter most of the file agrees on.

    Agreement rather than the first line, because a report title above the
    header splits into one field under every delimiter and would otherwise
    decide the answer. The winner is the one where the largest number of lines
    share the same field count.
    """
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
        # More lines agreeing wins; ties go to the delimiter that yields more
        # columns, since a stray comma inside a semicolon file splits fewer.
        if (agreeing, modal) > (best_score, best_fields - 1):
            best, best_score, best_fields = delimiter, agreeing, modal + 1

    return best


def _header_offset(sample: str, delimiter: str) -> int:
    """Rows to skip before the header.

    A sheet that opens with "Monthly Sales Report" and a blank line used to
    fail outright, because the first line has one field and the rest have many.
    The header is the first line carrying as many fields as the row below it.
    """
    lines = sample.splitlines()[: MAX_PREAMBLE_LINES + 2]
    for index, line in enumerate(lines[:-1]):
        if not line.strip():
            continue
        fields = _fields_outside_quotes(line, delimiter) + 1
        following = [other for other in lines[index + 1 : index + 4] if other.strip()]
        if (
            fields > 1
            and following
            and _fields_outside_quotes(following[0], delimiter) + 1 == fields
        ):
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
    """Rows carrying more fields than the header has columns.

    Polars is told to truncate them, because refusing the whole file over one
    stray delimiter helps nobody. But truncation drops real values off the end
    of a row, and doing that in silence is how a file imports cleanly and
    forecasts something else. The count is reported instead.
    """
    lines = [line for line in text.splitlines()[skip:] if line.strip()]
    return sum(1 for line in lines[1:] if _fields_outside_quotes(line, delimiter) + 1 > width)


#: How many rows of a sheet to look at when deciding whether it holds a table.
SHEET_PROBE_ROWS = 40


def _read_excel(path: Path) -> pl.DataFrame:
    """The sheet that holds the data, not simply the first one.

    A workbook that opens on a cover sheet, a parameters tab or a chart used to
    import as whatever that sheet happened to contain. The widest sheet with
    real rows under its header is the table; ties go to the earliest, which is
    where the main tab almost always sits.
    """
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
    """Carry a merged label down the rows it spans.

    Excel stores a vertical merge as the value in the top cell and nothing
    underneath. Read literally, a sheet with the region written once per block
    yields one labelled row and a column of nulls below it — and the rows that
    lost their label are dropped or pooled later without a word.
    """
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


#: A column filled in less often than this, and only in runs, is a merged
#: label rather than a column with missing values.
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
    """Trailing blank lines arrive as rows of nothing; they are not data."""
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
    """Read the numbers a spreadsheet wrote as text.

    There is one coercion path and it is the locale-aware one in
    `app.datasets.coercion`. Stripping every comma as decoration before asking
    what the comma *meant* reads the German ``1.234,56`` as 1.23456 — a
    thousandfold error in the forecast target, on a file that looked like it
    imported cleanly, in the half of the world that writes its decimals that
    way. Two coercions cannot both be right, so there is no longer a second.
    """
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
