"""Turning what a customer exported into values a forecast can use.

Real files do not arrive as clean floats and ISO dates. They arrive as
``$1,234.56`` out of Excel, ``1.234,56`` out of a German ERP, ``(890.00)`` out
of an accounting package, ``45292`` out of a spreadsheet that lost its date
formatting, and ``01/02/2024`` which means the first of February in most of the
world and the second of January in the United States.

Two rules run through this module.

The first is that a value is only accepted when the whole column agrees. A
convention is chosen from a sample, applied to every row, and kept only if it
explains nearly all of them — so a stray token cannot drag a column into the
wrong reading.

The second is that a guess this consequential must announce itself. Where the
data genuinely cannot settle the question — and day-versus-month order often
cannot — the result says so rather than picking quietly, and the caller is
expected to surface it and to offer the override.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import polars as pl

# How much of a column a convention has to explain before it is believed.
AGREEMENT = 0.8
# Enough rows to settle a convention without scanning millions.
SAMPLE_ROWS = 512

# Anything outside this is not a date somebody is forecasting from, and is far
# more likely to be a number that happened to survive a format string.
MIN_YEAR = 1900
MAX_YEAR = 2100

# Excel counts days from 1899-12-30 (its leap-year bug included). The bounds are
# roughly 1954 to 2064, which is where a real serial date sits.
EXCEL_EPOCH = date(1899, 12, 30)
EXCEL_MIN = 20_000
EXCEL_MAX = 60_000

# Unix seconds over the same era.
EPOCH_MIN = 315_532_800  # 1980-01-01
EPOCH_MAX = 4_102_444_800  # 2100-01-01


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
    #: True when day-first and month-first both explain the column, so the
    #: reading was chosen by heuristic and could be wrong.
    ambiguous: bool = False
    #: How the order was settled, for the message shown to whoever uploaded it.
    order_evidence: str = ""


# --------------------------------------------------------------------- numbers

_CURRENCY = "".join(chr(c) for c in range(0x20A0, 0x20C0)) + "$£€¥₹¢₩₽"
_STRIP_EDGES = " \t\r\n\"'` "
#: The spaces locales group digits with: non-breaking, narrow, thin.
_GROUPING_SPACES = "\u00a0\u202f\u2009"
#: A trailing unit — "kg", "units", "pcs" — after the digits. Written as a
#: keep-the-front rewrite rather than a look-behind, because the regex engine
#: polars uses supports no look-around at all.
_TRAILING_UNIT_KEEP = r"^(.*\d[\d.,]*)\s*[A-Za-z_/]+\.?$"
_TRAILING_UNIT = re.compile(_TRAILING_UNIT_KEEP)
_LEADING_SIGN_WORD = re.compile(r"^(?:approx|about|ca)\.?\s*", re.IGNORECASE)


def _strip_symbols(token: str) -> tuple[str, bool, bool]:
    """Return the numeric core of a token, plus accounting-negative/percent flags."""
    text = token.strip(_STRIP_EDGES)
    text = _LEADING_SIGN_WORD.sub("", text)

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()

    text = _TRAILING_UNIT.sub(r"\1", text).strip()
    text = "".join(ch for ch in text if ch not in _CURRENCY and unicodedata.category(ch) != "Sc")
    # Non-breaking and thin spaces are group separators in several locales.
    for space in _GROUPING_SPACES:
        text = text.replace(space, "")
    return text.strip(), negative, percent


_NUMERIC_CORE = re.compile(r"^[+-]?\d[\d.,]*$")


def _decimal_separator(cores: list[str]) -> str:
    """Whether this column writes 1.234,56 or 1,234.56."""
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

    # A column carrying both separators settles it outright: the later one is
    # the decimal point.
    if comma_last or dot_last:
        return "," if comma_last > dot_last else "."

    def looks_grouped(tokens: list[str], separator: str) -> bool:
        """1,234,567 is grouping; 1,23 is a decimal comma."""
        if not tokens:
            return False
        grouped = 0
        for token in tokens:
            parts = token.lstrip("+-").split(separator)
            if (len(parts) > 2 and all(len(p) == 3 for p in parts[1:])) or (
                len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3
            ):
                grouped += 1
        return grouped >= AGREEMENT * len(tokens)

    if comma_only and not dot_only:
        return "." if looks_grouped(comma_only, ",") else ","
    if dot_only and not comma_only:
        # A dot is the decimal point unless every value is grouped like 1.234.567.
        return "," if looks_grouped(dot_only, ".") else "."
    return "."


def coerce_numeric(series: pl.Series) -> NumericParse | None:
    """Read a column of formatted numbers, or return None if it is not one."""
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

    decimal = _decimal_separator(cores)
    group = "." if decimal == "," else ","

    cleaned = text.str.strip_chars(_STRIP_EDGES)
    negatives = cleaned.str.starts_with("(") & cleaned.str.ends_with(")")

    cleaned = (
        cleaned.str.replace_all(r"^\(", "")
        .str.replace_all(r"\)$", "")
        .str.replace_all(f"[{_GROUPING_SPACES}]", "")
        .str.replace_all(f"[{re.escape(_CURRENCY)}]", "")
        .str.replace_all(r"%$", "")
        .str.replace_all(_TRAILING_UNIT_KEEP, "$1")
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


# ----------------------------------------------------------------------- dates

#: Formats with no day/month ambiguity, tried before anything that has.
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

#: Same separator, opposite meaning. Only ever tried as a matched pair, and
#: four-digit years first so "15/01/2024" can never be read as the year 20.
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


def _plausible(parsed: pl.Series) -> bool:
    """Reject a format that technically matched but produced impossible years.

    This is what stops "1/5/24" being read as the year 24 and stored as
    0024-05-01 — strptime accepts it happily, and nothing downstream would
    ever question a date it was handed.
    """
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
    """Decide day-first vs month-first. Returns (day_first, ambiguous, evidence).

    The data settles it whenever either position exceeds twelve. When neither
    does, a regular series still gives it away: a monthly file holds its
    day-of-month fixed and varies the month, so the position that never moves
    is the day.
    """
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
    """Excel serials and Unix seconds — only where the column claims to be a date.

    Without that gate a revenue column of 45,000 would become a date in 2024.
    """
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


def _period_dates(text: pl.Series, total: int) -> DateParse | None:
    """2024Q1, Q1 2024 and 2024-W03, none of which strptime handles."""

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

    # These readers are Python callables run per row, so they are only ever
    # pointed at the full column once a sample says it is worth it. Reaching
    # here is the last resort for every column that is not a date, and an
    # ungated map_elements over a few hundred thousand order references cost
    # more than every other check in the profiler combined.
    sample = text.drop_nulls().head(SAMPLE_ROWS)
    if sample.len() == 0:
        return None

    for reader, label in ((quarter, "YYYYQn"), (iso_week, "ISO week")):
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
) -> DateParse | None:
    """Read a column of dates, or return None if it is not one.

    `day_first` forces the reading of ambiguous slash dates; left as None the
    column decides for itself and reports whether it could.
    """
    if series.dtype in (pl.Date, pl.Datetime):
        values = series.cast(pl.Date, strict=False)
        return DateParse(values, "native date", int(values.drop_nulls().len()))

    non_null_count = int(series.drop_nulls().len())
    if non_null_count == 0:
        return None

    if series.dtype.is_numeric():
        # An 8-digit integer is a date shape in its own right; anything else
        # numeric needs the column name to vouch for it.
        digits = series.cast(pl.Utf8, strict=False)
        compact = _try_format(digits, "%Y%m%d")
        if _rate(compact, non_null_count) >= AGREEMENT and compact is not None:
            return DateParse(
                compact.rename(series.name), "YYYYMMDD", int(compact.drop_nulls().len())
            )
        return _numeric_dates(series, name_suggests_date=name_suggests_date)

    text = series.cast(pl.Utf8, strict=False)
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
                    # Only the preferred reading is a guess; reaching the
                    # fallback means the data ruled the other one out.
                    ambiguous=ambiguous and label == ordered[1],
                    order_evidence=evidence if label == ordered[1] else "",
                )

    return _period_dates(text, non_null_count)
