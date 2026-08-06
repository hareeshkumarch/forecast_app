from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

import polars as pl

from app.forecasting.frequency import infer_frequency
from app.models.enums import ColumnKind, ColumnRole, ForecastFrequency

CURRENCY_NAME_HINTS = (
    "revenue",
    "sales",
    "amount",
    "value",
    "spend",
    "cost",
    "price",
    "gmv",
    "bookings",
)

ISO_SYMBOLS: dict[str, str] = {
    "usd": "$",
    "eur": "€",
    "gbp": "£",
    "jpy": "¥",
    "cny": "¥",
    "inr": "₹",
    "krw": "₩",
    "rub": "₽",
    "ngn": "₦",
    "brl": "R$",
    "chf": "CHF ",
    "sek": "kr ",
    "nok": "kr ",
    "dkk": "kr ",
    "pln": "zł ",
    "try": "₺",
    "cad": "$",
    "aud": "$",
    "nzd": "$",
    "sgd": "$",
    "hkd": "$",
    "mxn": "$",
    "zar": "R",
    "ils": "₪",
    "thb": "฿",
    "php": "₱",
    "vnd": "₫",
}

_ISO_PATTERN = re.compile(rf"(?<![a-z]) ?({'|'.join(ISO_SYMBOLS)})(?![a-z])")


def is_currency_like(column: str) -> bool:
    lowered = column.lower()
    if any(word in lowered for word in CURRENCY_NAME_HINTS):
        return True
    return currency_symbol(column) is not None


def currency_symbol(column: str) -> str | None:
    for character in column:
        if unicodedata.category(character) == "Sc":
            return character

    match = _ISO_PATTERN.search(column.lower())
    return ISO_SYMBOLS[match.group(1)] if match else None


DATE_NAME_HINTS = (
    "date",
    "day",
    "month",
    "week",
    "period",
    "time",
    "timestamp",
    "ds",
    "dt",
    "yearmonth",
    "year_month",
    "fiscal",
)
TARGET_NAME_HINTS = (
    "revenue",
    "sales",
    "amount",
    "value",
    "total",
    "demand",
    "volume",
    "quantity",
    "qty",
    "units",
    "count",
    "spend",
    "cost",
    "gmv",
    "bookings",
    "target",
    "y",
    "actual",
    "net",
    "gross",
)
DIMENSION_NAME_HINTS = (
    "region",
    "country",
    "market",
    "territory",
    "category",
    "segment",
    "product",
    "sku",
    "channel",
    "brand",
    "department",
    "store",
    "customer",
    "type",
    "group",
    "division",
)
WEIGHT_NAME_HINTS = ("weight", "units", "quantity", "qty", "volume")


DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m",
    "%b %Y",
    "%B %Y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y%m%d",
)


@dataclass(slots=True)
class ColumnProfile:
    name: str
    position: int
    kind: ColumnKind
    role: ColumnRole
    dtype: str
    null_count: int
    distinct_count: int
    min_value: str | None
    max_value: str | None
    mean_value: float | None
    sample_values: list = field(default_factory=list)
    is_date_candidate: bool = False
    is_target_candidate: bool = False

    date_score: float = 0.0
    target_score: float = 0.0
    reason: str = ""


@dataclass(slots=True)
class DatasetProfileResult:
    row_count: int
    column_count: int
    missing_value_count: int
    columns: list[ColumnProfile]
    date_range_start: date | None
    date_range_end: date | None
    detected_frequency: ForecastFrequency | None
    preview_rows: list[dict]
    warnings: list[str] = field(default_factory=list)


def _name_score(name: str, hints: tuple[str, ...]) -> float:
    lowered = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    tokens = set(lowered.split())

    for hint in hints:
        if hint in tokens:
            return 1.0
    for hint in hints:
        if hint in lowered:
            return 0.6
    return 0.0


def _try_parse_dates(series: pl.Series) -> pl.Series | None:
    non_null = series.drop_nulls()
    if non_null.len() == 0:
        return None

    if series.dtype in (pl.Date, pl.Datetime):
        return series.cast(pl.Date, strict=False)

    as_string = non_null.cast(pl.Utf8, strict=False)
    if as_string is None:
        return None

    for fmt in DATE_FORMATS:
        try:
            parsed = as_string.str.strptime(pl.Date, format=fmt, strict=False)
        except Exception:
            continue
        matched = parsed.drop_nulls().len()
        if matched >= 0.8 * non_null.len():
            return series.cast(pl.Utf8, strict=False).str.strptime(
                pl.Date, format=fmt, strict=False
            )

    return None


def _classify(series: pl.Series, parsed_dates: pl.Series | None) -> ColumnKind:
    if parsed_dates is not None:
        return ColumnKind.DATE
    dtype = series.dtype
    if dtype == pl.Boolean:
        return ColumnKind.BOOLEAN
    if dtype.is_numeric():
        return ColumnKind.NUMERIC

    non_null = series.drop_nulls()
    if non_null.len() and series.n_unique() <= max(50, non_null.len() * 0.2):
        return ColumnKind.CATEGORICAL
    return ColumnKind.TEXT


def _stringify(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    text = str(value)
    return text[:200]


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def profile_frame(frame: pl.DataFrame, *, preview_rows: int = 8) -> DatasetProfileResult:
    profiles: list[ColumnProfile] = []
    warnings: list[str] = []
    total_missing = 0

    parsed_date_columns: dict[str, pl.Series] = {}

    for position, name in enumerate(frame.columns):
        series = frame[name]
        null_count = int(series.null_count())
        total_missing += null_count

        parsed = _try_parse_dates(series)
        if parsed is not None:
            parsed_date_columns[name] = parsed

        kind = _classify(series, parsed)
        non_null = series.drop_nulls()

        min_value = max_value = None
        mean_value: float | None = None

        if kind is ColumnKind.DATE and parsed is not None:
            valid = parsed.drop_nulls()
            if valid.len():
                min_value = _stringify(valid.min())
                max_value = _stringify(valid.max())
        elif kind is ColumnKind.NUMERIC and non_null.len():
            min_value = _stringify(non_null.min())
            max_value = _stringify(non_null.max())
            mean_raw = non_null.mean()
            mean_value = (
                float(mean_raw)
                if isinstance(mean_raw, int | float) and not isinstance(mean_raw, bool)
                else None
            )
        elif non_null.len():
            min_value = _stringify(non_null.min())
            max_value = _stringify(non_null.max())

        profile = ColumnProfile(
            name=name,
            position=position,
            kind=kind,
            role=ColumnRole.IGNORED,
            dtype=str(series.dtype),
            null_count=null_count,
            distinct_count=int(series.n_unique()),
            min_value=min_value,
            max_value=max_value,
            mean_value=mean_value,
            sample_values=[_stringify(v) for v in non_null.head(5).to_list()],
        )

        _score_column(profile, frame.height)
        profiles.append(profile)

    _assign_roles(profiles)

    date_start: date | None = None
    date_end: date | None = None
    detected_frequency: ForecastFrequency | None = None

    time_column = next((p for p in profiles if p.role is ColumnRole.TIME), None)
    if time_column and time_column.name in parsed_date_columns:
        values = parsed_date_columns[time_column.name].drop_nulls()
        if values.len():
            date_start = _as_date(values.min())
            date_end = _as_date(values.max())
            detected_frequency = infer_frequency(sorted(set(values.to_list())))
            if detected_frequency is None:
                warnings.append(
                    f"Couldn't infer a regular frequency from '{time_column.name}'. "
                    "Pick one manually — the data may have irregular gaps."
                )

    if frame.height < 12:
        warnings.append(
            f"Only {frame.height} rows. Forecast quality will be limited and "
            "model selection may fall back to a simple baseline."
        )

    cells = max(1, frame.height * frame.width)
    missing_pct = total_missing / cells * 100
    if missing_pct > 20:
        warnings.append(f"{missing_pct:.1f}% of cells are empty. Consider cleaning the data first.")

    if not any(p.is_date_candidate for p in profiles):
        warnings.append(
            "No column could be parsed as a date. A time column is required to forecast."
        )
    if not any(p.is_target_candidate for p in profiles):
        warnings.append("No numeric column was found to use as a forecast target.")

    preview = frame.head(preview_rows).to_dicts()
    preview = [{k: _stringify(v) for k, v in row.items()} for row in preview]

    return DatasetProfileResult(
        row_count=frame.height,
        column_count=frame.width,
        missing_value_count=total_missing,
        columns=profiles,
        date_range_start=date_start,
        date_range_end=date_end,
        detected_frequency=detected_frequency,
        preview_rows=preview,
        warnings=warnings,
    )


def _score_column(profile: ColumnProfile, row_count: int) -> None:
    reasons: list[str] = []

    if profile.kind is ColumnKind.DATE:
        score = 0.6
        reasons.append("parses as dates")

        name_signal = _name_score(profile.name, DATE_NAME_HINTS)
        score += 0.25 * name_signal
        if name_signal:
            reasons.append("name suggests a date")

        if row_count:
            uniqueness = profile.distinct_count / row_count
            if uniqueness > 0.9:
                score += 0.15
                reasons.append("one row per period")
            elif uniqueness > 0.05:
                score += 0.08

        if profile.null_count:
            score -= 0.2 * (profile.null_count / max(1, row_count))
            reasons.append(f"{profile.null_count} missing dates")

        profile.date_score = max(0.0, min(1.0, score))
        profile.is_date_candidate = profile.date_score >= 0.5

    if profile.kind is ColumnKind.NUMERIC:
        score = 0.45
        reasons.append("numeric")

        name_signal = _name_score(profile.name, TARGET_NAME_HINTS)
        score += 0.35 * name_signal
        if name_signal >= 1.0:
            reasons.append("name matches a common measure")
        elif name_signal:
            reasons.append("name hints at a measure")

        if _name_score(profile.name, WEIGHT_NAME_HINTS) >= 1.0:
            score -= 0.12
            reasons.append("more likely a weight than a target")

        if (
            row_count
            and profile.distinct_count / row_count > 0.98
            and _name_score(profile.name, ("id", "key", "index", "row", "number"))
        ):
            score -= 0.5
            reasons.append("looks like an identifier")

        if profile.distinct_count <= 1:
            score -= 0.4
            reasons.append("constant value")

        if row_count and profile.null_count / row_count > 0.3:
            score -= 0.2
            reasons.append("sparsely populated")

        profile.target_score = max(0.0, min(1.0, score))
        profile.is_target_candidate = profile.target_score >= 0.4

    profile.reason = ", ".join(reasons) if reasons else "no strong signal"


def _assign_roles(profiles: list[ColumnProfile]) -> None:
    dates = sorted(
        (p for p in profiles if p.is_date_candidate), key=lambda p: p.date_score, reverse=True
    )
    targets = sorted(
        (p for p in profiles if p.is_target_candidate), key=lambda p: p.target_score, reverse=True
    )

    if dates:
        dates[0].role = ColumnRole.TIME
    if targets:
        targets[0].role = ColumnRole.TARGET

    for profile in profiles:
        if profile.role is not ColumnRole.IGNORED:
            continue
        if profile.kind is ColumnKind.CATEGORICAL:
            profile.role = ColumnRole.DIMENSION
        elif profile.kind is ColumnKind.NUMERIC:
            profile.role = (
                ColumnRole.WEIGHT
                if _name_score(profile.name, WEIGHT_NAME_HINTS) >= 1.0
                else ColumnRole.MEASURE
            )


def suggestions(
    profiles: list[ColumnProfile], role: str
) -> list[tuple[str, ColumnKind, float, str]]:
    if role == "time":
        pool = [(p, p.date_score) for p in profiles if p.is_date_candidate]
    elif role == "target":
        pool = [(p, p.target_score) for p in profiles if p.is_target_candidate]
    else:
        pool = [
            (p, 0.6 + 0.4 * _name_score(p.name, DIMENSION_NAME_HINTS))
            for p in profiles
            if p.kind is ColumnKind.CATEGORICAL
        ]

    pool.sort(key=lambda item: item[1], reverse=True)
    return [(p.name, p.kind, round(score, 3), p.reason) for p, score in pool]
