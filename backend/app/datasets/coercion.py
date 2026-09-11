from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import polars as pl

AGREEMENT = 0.8
SAMPLE_ROWS = 512

MIN_YEAR = 1900
MAX_YEAR = 2100

EXCEL_EPOCH = date(1899, 12, 30)
EXCEL_MIN = 20_000
EXCEL_MAX = 60_000

EPOCH_MIN = 315_532_800
EPOCH_MAX = 4_102_444_800


@dataclass(slots=True)
class NumericParse:
    values: pl.Series
    style: str
    matched: int


@dataclass(slots=True)
class DateParse:
    values: pl.Series
    layout: str
    matched: int
    ambiguous: bool = False
    order_evidence: str = ""


_CURRENCY = "".join(chr(c) for c in range(0x20A0, 0x20C0)) + "$£€¥₹¢₩₽"
_GROUPING_SPACES = "\u00a0\u202f\u2009 "
_STRIP_EDGES = " \t\r\n\"'`" + _GROUPING_SPACES
_TRAILING_UNIT_KEEP = r"^(.*\d[\d.,]*)\s*[A-Za-z_/]+\.?$"
_TRAILING_UNIT = re.compile(_TRAILING_UNIT_KEEP)
_LEADING_SIGN_WORD_KEEP = r"^(?:approx|about|ca)\.?\s*"
_LEADING_SIGN_WORD = re.compile(_LEADING_SIGN_WORD_KEEP, re.IGNORECASE)
_SPACE_GROUP_KEEP = rf"(\d)[{_GROUPING_SPACES}](\d)"
_SPACE_GROUP = re.compile(_SPACE_GROUP_KEEP)
_EXPONENT = re.compile(r"[eE][+-]?\d+$")
_YEAR_NAME = re.compile(
    r"(?:^|[^a-z])(?:year|yr|fy|jahr|ann[eé]e|anno|a[nñ]o|ejercicio)s?(?:[^a-z]|$)",
    re.IGNORECASE,
)
_BARE_YEAR = re.compile(r"^(?:19|20)\d{2}$")


def _strip_symbols(token: str) -> tuple[str, bool, bool]:
    text = token.strip(_STRIP_EDGES)
    text = _LEADING_SIGN_WORD.sub("", text)

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    elif text.endswith("-") and len(text) > 1:
        negative = True
        text = text[:-1].strip()

    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()

    text = _TRAILING_UNIT.sub(r"\1", text).strip()
    text = "".join(ch for ch in text if ch not in _CURRENCY and unicodedata.category(ch) != "Sc")
    text = _SPACE_GROUP.sub(r"\1\2", text.strip(_STRIP_EDGES))
    return text.strip(_STRIP_EDGES), negative, percent


_NUMERIC_CORE = re.compile(r"^[+-]?\d[\d.,]*(?:[eE][+-]?\d+)?$")


def _decimal_separator(cores: list[str]) -> str:
    comma_last = dot_last = 0
    comma_only: list[str] = []
    dot_only: list[str] = []

    for core in cores:
        has_comma, has_dot = "," in core, "." in core
        if has_comma and has_dot:
            if core.rfind(",") > core.rfind("."):
                comma_last += 1
            else:
                dot_last += 1
        elif has_comma:
            comma_only.append(core)
        elif has_dot:
            dot_only.append(core)

    if comma_last or dot_last:
        return "," if comma_last > dot_last else "."

    def looks_grouped(tokens: list[str], separator: str) -> bool:
        if not tokens:
            return False
        grouped = 0
        for token in tokens:
            parts = token.lstrip("+-").split(separator)
            head, tail = parts[0], parts[1:]
            if not tail or not head or len(head) > 3:
                continue
            if all(len(part) == 3 for part in tail) or (
                len(tail) > 1 and len(tail[-1]) == 3 and all(len(part) == 2 for part in tail[:-1])
            ):
                grouped += 1
        return grouped >= AGREEMENT * len(tokens)

    if comma_only and not dot_only:
        return "." if looks_grouped(comma_only, ",") else ","
    if dot_only and not comma_only:
        return "," if looks_grouped(dot_only, ".") else "."
    return "."


def _is_year_label(name: str, cores: list[str]) -> bool:
    return bool(_YEAR_NAME.search(name)) and all(_BARE_YEAR.match(core) for core in cores)


def coerce_numeric(series: pl.Series) -> NumericParse | None:
    if series.dtype.is_numeric():
        return NumericParse(
            values=series.cast(pl.Float64, strict=False),
            style="plain",
            matched=int(series.drop_nulls().len()),
        )
    if series.dtype == pl.Boolean:
        return None

    text = series.cast(pl.Utf8, strict=False)
    non_null = text.drop_nulls()
    if non_null.len() == 0:
        return None

    sample = non_null.head(SAMPLE_ROWS).to_list()
    cores: list[str] = []
    saw_percent = saw_accounting = saw_symbol = False

    for token in sample:
        core, negative, percent = _strip_symbols(str(token))
        if not _NUMERIC_CORE.match(core):
            continue
        saw_accounting |= negative
        saw_percent |= percent
        saw_symbol |= core != str(token).strip(_STRIP_EDGES)
        cores.append(core)

    if len(cores) < AGREEMENT * len(sample):
        return None
    if _is_year_label(series.name, cores):
        return None

    decimal = _decimal_separator([_EXPONENT.sub("", core) for core in cores])
    group = "." if decimal == "," else ","

    cleaned = text.str.strip_chars(_STRIP_EDGES)
    negatives = (cleaned.str.starts_with("(") & cleaned.str.ends_with(")")) | (
        cleaned.str.ends_with("-") & (cleaned.str.len_chars() > 1)
    )

    cleaned = (
        cleaned.str.replace_all(rf"(?i){_LEADING_SIGN_WORD_KEEP}", "")
        .str.replace_all(r"^\(", "")
        .str.replace_all(r"\)$", "")
        .str.replace_all(r"-$", "")
        .str.replace_all(f"[{re.escape(_CURRENCY)}]", "")
        .str.replace_all(r"%$", "")
        .str.replace_all(_TRAILING_UNIT_KEEP, "$1")
        .str.strip_chars(_STRIP_EDGES)
        .str.replace_all(_SPACE_GROUP_KEEP, "${1}${2}")
        .str.replace_all(re.escape(group), "")
    )
    if decimal == ",":
        cleaned = cleaned.str.replace_all(",", ".")

    values = cleaned.cast(pl.Float64, strict=False)
    matched = int(values.drop_nulls().len())
    if matched < AGREEMENT * non_null.len():
        return None

    values = pl.select(pl.when(negatives).then(-values.abs()).otherwise(values)).to_series()

    if saw_percent:
        style = "percent"
    elif saw_accounting:
        style = "accounting"
    elif decimal == ",":
        style = "european"
    elif saw_symbol:
        style = "currency"
    else:
        style = "grouped"

    return NumericParse(values=values.rename(series.name), style=style, matched=matched)


UNAMBIGUOUS_FORMATS: tuple[tuple[str, str], ...] = (
    ("%Y-%m-%d", "YYYY-MM-DD"),
    ("%Y/%m/%d", "YYYY/MM/DD"),
    ("%Y.%m.%d", "YYYY.MM.DD"),
    ("%Y-%m-%dT%H:%M:%S%.f", "ISO timestamp"),
    ("%Y-%m-%dT%H:%M:%S", "ISO timestamp"),
    ("%Y-%m-%d %H:%M:%S%.f", "ISO timestamp"),
    ("%Y-%m-%d %H:%M:%S", "ISO timestamp"),
    ("%Y-%m", "YYYY-MM"),
    ("%Y%m%d", "YYYYMMDD"),
    ("%d %b %Y", "DD Mon YYYY"),
    ("%d %B %Y", "DD Month YYYY"),
    ("%b %d, %Y", "Mon DD, YYYY"),
    ("%B %d, %Y", "Month DD, YYYY"),
    ("%b %d %Y", "Mon DD YYYY"),
    ("%b %Y", "Mon YYYY"),
    ("%B %Y", "Month YYYY"),
)

DAY_FIRST_FORMATS: tuple[str, ...] = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d.%m.%y",
)
MONTH_FIRST_FORMATS: tuple[str, ...] = (
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%m.%d.%Y",
    "%m/%d/%y",
    "%m-%d-%y",
    "%m.%d.%y",
)

_TWO_PART = re.compile(r"^\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})")
_QUARTER = re.compile(r"^\s*(\d{4})\s*[-/ ]?\s*[Qq]\s*([1-4])\s*$")
_QUARTER_FIRST = re.compile(r"^\s*[Qq]\s*([1-4])\s*[-/ ]?\s*(\d{4})\s*$")
_ISO_WEEK = re.compile(r"^\s*(\d{4})\s*[-/ ]?[Ww]\s*(\d{1,2})\s*$")
_ZONE_SUFFIX = r"(?:[Zz]|[+-]\d{2}:?\d{2})$"
_FISCAL = re.compile(r"^\s*FY\s*(\d{2}|\d{4})\s*[-/ ]?\s*[PM]\s*(\d{1,2})\s*$", re.IGNORECASE)


def _plausible(parsed: pl.Series) -> bool:
    valid = parsed.drop_nulls()
    if valid.len() == 0:
        return False
    years = valid.dt.year()
    lowest, highest = years.min(), years.max()
    if not isinstance(lowest, int) or not isinstance(highest, int):
        return False
    return lowest >= MIN_YEAR and highest <= MAX_YEAR


def _try_format(text: pl.Series, fmt: str) -> pl.Series | None:
    try:
        parsed = text.str.strptime(pl.Date, format=fmt, strict=False)
    except Exception:
        return None
    return parsed if _plausible(parsed) else None


def _rate(parsed: pl.Series | None, total: int) -> float:
    if parsed is None or total == 0:
        return 0.0
    return parsed.drop_nulls().len() / total


def _resolve_order(sample: list[str]) -> tuple[bool, bool, str]:
    firsts: list[int] = []
    seconds: list[int] = []
    for token in sample:
        match = _TWO_PART.match(str(token))
        if match:
            firsts.append(int(match.group(1)))
            seconds.append(int(match.group(2)))

    if not firsts:
        return False, False, ""

    if max(firsts) > 12:
        return True, False, "the first number passes 12, so it is the day"
    if max(seconds) > 12:
        return False, False, "the second number passes 12, so it is the day"

    unique_first, unique_second = len(set(firsts)), len(set(seconds))
    if unique_second == 1 and unique_first > 1:
        return False, False, "the second number never changes, so it is the day of the month"
    if unique_first == 1 and unique_second > 1:
        return True, False, "the first number never changes, so it is the day of the month"

    return (
        True,
        True,
        "every value fits both day/month and month/day, so the order cannot be read from the data",
    )


def _numeric_dates(series: pl.Series, *, name_suggests_date: bool) -> DateParse | None:
    if not name_suggests_date or not series.dtype.is_numeric():
        return None

    whole = series.cast(pl.Int64, strict=False)
    valid = whole.drop_nulls()
    if valid.len() == 0:
        return None

    low, high = int(valid.min()), int(valid.max())  # type: ignore[arg-type]

    if low >= EXCEL_MIN and high <= EXCEL_MAX:
        values = whole.map_elements(
            lambda d: EXCEL_EPOCH + timedelta(days=int(d)) if d is not None else None,
            return_dtype=pl.Date,
        )
        return DateParse(values.rename(series.name), "Excel serial", int(values.drop_nulls().len()))

    if low >= EPOCH_MIN and high <= EPOCH_MAX:
        values = whole.map_elements(
            lambda s: datetime.utcfromtimestamp(int(s)).date() if s is not None else None,
            return_dtype=pl.Date,
        )
        return DateParse(values.rename(series.name), "Unix seconds", int(values.drop_nulls().len()))

    return None


def _fiscal_start_month() -> int:
    from app.core.config import settings

    return int(settings.fiscal_year_start_month)


def _period_dates(
    text: pl.Series, total: int, fiscal_start_month: int | None = None
) -> DateParse | None:
    def quarter(value: str | None) -> date | None:
        if value is None:
            return None
        match = _QUARTER.match(value) or _QUARTER_FIRST.match(value)
        if not match:
            return None
        year, index = (
            (int(match.group(1)), int(match.group(2)))
            if _QUARTER.match(value)
            else (int(match.group(2)), int(match.group(1)))
        )
        if not MIN_YEAR <= year <= MAX_YEAR:
            return None
        return date(year, 3 * (index - 1) + 1, 1)

    def iso_week(value: str | None) -> date | None:
        if value is None:
            return None
        match = _ISO_WEEK.match(value)
        if not match:
            return None
        year, week = int(match.group(1)), int(match.group(2))
        if not (MIN_YEAR <= year <= MAX_YEAR and 1 <= week <= 53):
            return None
        try:
            return date.fromisocalendar(year, week, 1)
        except ValueError:
            return None

    sample = text.drop_nulls().head(SAMPLE_ROWS)
    if sample.len() == 0:
        return None

    def fiscal(value: str | None) -> date | None:
        if value is None:
            return None
        match = _FISCAL.match(value)
        if not match:
            return None
        year_text, period = match.group(1), int(match.group(2))
        if not 1 <= period <= 12:
            return None
        year = int(year_text)
        if len(year_text) == 2:
            year += 2000
        if not MIN_YEAR <= year <= MAX_YEAR:
            return None

        start = fiscal_start_month if fiscal_start_month is not None else _fiscal_start_month()
        offset = start - 1 + period - 1
        month = offset % 12 + 1
        return date(year + offset // 12, month, 1)

    for reader, label in ((quarter, "YYYYQn"), (iso_week, "ISO week"), (fiscal, "fiscal period")):
        probe = sample.map_elements(reader, return_dtype=pl.Date)
        if _rate(probe, sample.len()) < AGREEMENT:
            continue
        values = text.map_elements(reader, return_dtype=pl.Date)
        if _rate(values, total) >= AGREEMENT:
            return DateParse(values.rename(text.name), label, int(values.drop_nulls().len()))
    return None


def parse_dates(
    series: pl.Series,
    *,
    day_first: bool | None = None,
    name_suggests_date: bool = False,
    fiscal_start_month: int | None = None,
) -> DateParse | None:
    if series.dtype in (pl.Date, pl.Datetime):
        values = series.cast(pl.Date, strict=False)
        return DateParse(values, "native date", int(values.drop_nulls().len()))

    non_null_count = int(series.drop_nulls().len())
    if non_null_count == 0:
        return None

    if series.dtype.is_numeric():
        digits = series.cast(pl.Utf8, strict=False)
        compact = _try_format(digits, "%Y%m%d")
        if _rate(compact, non_null_count) >= AGREEMENT and compact is not None:
            return DateParse(
                compact.rename(series.name), "YYYYMMDD", int(compact.drop_nulls().len())
            )
        return _numeric_dates(series, name_suggests_date=name_suggests_date)

    text = series.cast(pl.Utf8, strict=False)
    text = text.str.replace(_ZONE_SUFFIX, "")
    sample = text.drop_nulls().head(SAMPLE_ROWS)
    sample_list = [str(v) for v in sample.to_list()]
    sample_count = sample.len()

    for fmt, label in UNAMBIGUOUS_FORMATS:
        if _rate(_try_format(sample, fmt), sample_count) < AGREEMENT:
            continue
        parsed = _try_format(text, fmt)
        if _rate(parsed, non_null_count) >= AGREEMENT and parsed is not None:
            return DateParse(parsed.rename(series.name), label, int(parsed.drop_nulls().len()))

    resolved_day_first, ambiguous, evidence = _resolve_order(sample_list)
    if day_first is not None:
        resolved_day_first, ambiguous = day_first, False
        evidence = f"the {'day/month' if day_first else 'month/day'} order was set by hand"

    ordered = (
        (DAY_FIRST_FORMATS, "DD/MM/YYYY")
        if resolved_day_first
        else (MONTH_FIRST_FORMATS, "MM/DD/YYYY")
    )
    fallback = (
        (MONTH_FIRST_FORMATS, "MM/DD/YYYY")
        if resolved_day_first
        else (DAY_FIRST_FORMATS, "DD/MM/YYYY")
    )

    for formats, label in (ordered, fallback):
        for fmt in formats:
            if _rate(_try_format(sample, fmt), sample_count) < AGREEMENT:
                continue
            parsed = _try_format(text, fmt)
            if _rate(parsed, non_null_count) >= AGREEMENT and parsed is not None:
                return DateParse(
                    values=parsed.rename(series.name),
                    layout=label,
                    matched=int(parsed.drop_nulls().len()),
                    ambiguous=ambiguous and label == ordered[1],
                    order_evidence=evidence if label == ordered[1] else "",
                )

    mixed = _mixed_formats(text, non_null_count, resolved_day_first)
    if mixed is not None:
        return mixed

    return _period_dates(text, non_null_count, fiscal_start_month)


MIXED_FORMAT_SHARE = 0.1


def _mixed_formats(text: pl.Series, total: int, day_first: bool) -> DateParse | None:
    candidates = [fmt for fmt, _label in UNAMBIGUOUS_FORMATS]
    candidates += DAY_FIRST_FORMATS if day_first else MONTH_FIRST_FORMATS

    readings = [
        parsed
        for fmt in candidates
        if (parsed := _try_format(text, fmt)) is not None
        and _rate(parsed, total) >= MIXED_FORMAT_SHARE
    ]
    if len(readings) < 2:
        return None

    merged = readings[0]
    for other in readings[1:]:
        merged = merged.fill_null(other)

    if _rate(merged, total) < AGREEMENT:
        return None
    return DateParse(merged.rename(text.name), "mixed formats", int(merged.drop_nulls().len()))


MIN_WIDE_PERIODS = 3


def period_columns(names: list[str]) -> dict[str, date]:
    found: dict[str, date] = {}
    for name in names:
        parsed = parse_dates(pl.Series("header", [str(name)]), name_suggests_date=False)
        if parsed is None:
            continue
        values = parsed.values.drop_nulls()
        if values.len():
            found[name] = values[0]
    return found


def unpivot_periods(
    frame: pl.DataFrame, *, period_name: str = "period", value_name: str = "value"
) -> tuple[pl.DataFrame, dict[str, date]] | None:
    periods = period_columns(list(frame.columns))
    if len(periods) < MIN_WIDE_PERIODS:
        return None

    identifiers = [name for name in frame.columns if name not in periods]

    measures: list[str] = []
    for name in periods:
        numeric = coerce_numeric(frame[name])
        if numeric is None:
            return None
        measures.append(name)

    long = frame.unpivot(
        index=identifiers or None,
        on=measures,
        variable_name=period_name,
        value_name=value_name,
    )
    long = long.with_columns(
        pl.col(period_name).replace_strict(
            {name: periods[name] for name in measures}, return_dtype=pl.Date
        ),
        coerce_numeric(long[value_name]).values.alias(value_name)  # type: ignore[union-attr]
        if coerce_numeric(long[value_name]) is not None
        else pl.col(value_name),
    )
    return long, periods
