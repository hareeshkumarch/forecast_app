from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

import polars as pl

from app.datasets.coercion import coerce_numeric, parse_dates, unpivot_periods
from app.forecasting.frequency import infer_frequency
from app.models.enums import ColumnKind, ColumnRole, ForecastFrequency, MeasureAggregation

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


RATE_NAME_HINTS = (
    "rate",
    "ratio",
    "percent",
    "pct",
    "share",
    "index",
    "score",
    "average",
    "avg",
    "mean",
    "median",
    "price",
    "temperature",
    "temp",
    "utilisation",
    "utilization",
    "margin",
    "yield",
    "level",
    "balance",
    "per_",
    "_per",
)


def is_rate_like(column: str) -> bool:
    lowered = column.lower()
    if any(word in lowered for word in RATE_NAME_HINTS):
        return not any(word in lowered for word in ("total", "sum", "count"))
    return False


def natural_aggregation(column: str) -> MeasureAggregation:
    return MeasureAggregation.MEAN if is_rate_like(column) else MeasureAggregation.SUM


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
STRONG_TARGET_HINTS = (
    "revenue",
    "sales",
    "demand",
    "bookings",
    "gmv",
    "turnover",
    "billings",
    "umsatz",
    "erlos",
    "ventas",
    "vendas",
    "facturacion",
    "ricavi",
    "fatturato",
    "omzet",
    "chiffre",
    "affaires",
    "receita",
    "salg",
    "myynti",
)

WEAK_TARGET_HINTS = (
    "amount",
    "value",
    "total",
    "volume",
    "quantity",
    "qty",
    "units",
    "count",
    "spend",
    "cost",
    "target",
    "actual",
    "net",
    "gross",
    "y",
    "menge",
    "cantidad",
    "quantite",
    "betrag",
    "wert",
)

TARGET_NAME_HINTS = STRONG_TARGET_HINTS + WEAK_TARGET_HINTS

NAME_ABBREVIATIONS: dict[str, str] = {
    "rev": "revenue",
    "revs": "revenue",
    "amt": "amount",
    "amnt": "amount",
    "qty": "quantity",
    "qnty": "quantity",
    "vol": "volume",
    "cnt": "count",
    "sls": "sales",
    "sl": "sales",
    "val": "value",
    "tot": "total",
    "net": "net",
    "gr": "gross",
    "dmd": "demand",
    "dt": "date",
    "dte": "date",
    "ts": "timestamp",
    "prd": "period",
    "per": "period",
    "yr": "year",
    "mth": "month",
    "wk": "week",
    "cust": "customer",
    "prod": "product",
    "cat": "category",
    "rgn": "region",
    "ctry": "country",
    "chan": "channel",
    "whs": "warehouse",
    "str": "store",
    "seg": "segment",
}

MIN_FUZZY_LENGTH = 5

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


MEASURE_NAME_HINTS = ("metric", "kpi", "measure", "indicator", "variable", "series")

MIXED_MEASURE_RATIO = 50.0

MAX_MEASURE_LABELS = 20

MAX_CATEGORICAL_VALUES = 200

MAX_AUTO_DIMENSION_VALUES = 60

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
    unreadable_count: int = 0
    sample_values: list = field(default_factory=list)
    is_date_candidate: bool = False
    is_target_candidate: bool = False

    date_score: float = 0.0
    target_score: float = 0.0
    reason: str = ""

    parsed_as: str = ""
    order_ambiguous: bool = False


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
    normalised: pl.DataFrame | None = field(default=None, repr=False)


def _tokens(name: str) -> set[str]:
    lowered = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered.lower()).strip()
    words = {word for word in lowered.split() if word}
    return words | {NAME_ABBREVIATIONS[word] for word in words if word in NAME_ABBREVIATIONS}


def name_score(name: str, hints: tuple[str, ...]) -> float:
    tokens = _tokens(name)
    if tokens & set(hints):
        return 1.0

    for token in tokens:
        if len(token) >= 3 and any(hint.startswith(token) for hint in hints):
            return 0.8

    lowered = " ".join(sorted(tokens))
    if any(hint in lowered for hint in hints):
        return 0.6

    for token in tokens:
        if len(token) >= MIN_FUZZY_LENGTH and any(_within_one_edit(token, hint) for hint in hints):
            return 0.5
    return 0.0


def _within_one_edit(token: str, hint: str) -> bool:
    if abs(len(token) - len(hint)) > 1:
        return False
    if token == hint:
        return True

    if len(token) == len(hint):
        differing = [
            index
            for index, (left, right) in enumerate(zip(token, hint, strict=True))
            if left != right
        ]
        if len(differing) == 1:
            return True
        if len(differing) == 2:
            first, second = differing
            return (
                second == first + 1
                and token[first] == hint[second]
                and token[second] == hint[first]
            )
        return False

    longer, shorter = (token, hint) if len(token) > len(hint) else (hint, token)
    return any(longer[:index] + longer[index + 1 :] == shorter for index in range(len(longer)))


def _try_parse_dates(series: pl.Series, *, name_suggests_date: bool = False) -> pl.Series | None:
    parsed = parse_dates(series, name_suggests_date=name_suggests_date)
    return None if parsed is None else parsed.values


def _classify(
    series: pl.Series,
    parsed_dates: pl.Series | None,
    numeric: pl.Series | None = None,
    *,
    distinct_count: int | None = None,
) -> ColumnKind:
    if parsed_dates is not None:
        return ColumnKind.DATE
    dtype = series.dtype
    if dtype == pl.Boolean:
        return ColumnKind.BOOLEAN
    if dtype.is_numeric() or numeric is not None:
        return ColumnKind.NUMERIC

    non_null = series.drop_nulls()
    if non_null.len() == 0:
        return ColumnKind.TEXT

    distinct = series.n_unique() if distinct_count is None else distinct_count
    ceiling = min(max(50, non_null.len() * 0.2), MAX_CATEGORICAL_VALUES)
    if distinct <= ceiling:
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


def profile_frame(
    frame: pl.DataFrame,
    *,
    preview_rows: int = 8,
    day_first: bool | None = None,
) -> DatasetProfileResult:
    profiles: list[ColumnProfile] = []
    warnings: list[str] = []
    total_missing = 0

    parsed_date_columns: dict[str, pl.Series] = {}

    reshaped = unpivot_periods(frame)
    if reshaped is not None:
        frame, periods = reshaped
        warnings.append(
            f"The {len(periods)} period columns across the top of this file were turned into "
            "rows, so every one of them can be forecast."
        )

    normalised: dict[str, pl.Series] = {}
    ambiguous_dates: list[str] = []
    unreadable_columns: dict[str, int] = {}

    for position, name in enumerate(frame.columns):
        series = frame[name]
        null_count = int(series.null_count())
        distinct_count = int(series.n_unique())

        name_suggests_date = name_score(name, DATE_NAME_HINTS) > 0.0
        date_parse = parse_dates(series, day_first=day_first, name_suggests_date=name_suggests_date)
        numeric_parse = None if date_parse is not None else coerce_numeric(series)

        parsed = None if date_parse is None else date_parse.values
        if parsed is not None:
            parsed_date_columns[name] = parsed
            if series.dtype not in (pl.Date, pl.Datetime):
                normalised[name] = parsed
            if date_parse is not None and date_parse.ambiguous:
                ambiguous_dates.append(name)
        elif numeric_parse is not None and not series.dtype.is_numeric():
            normalised[name] = numeric_parse.values

        unreadable = 0
        if name in normalised:
            unreadable = max(0, int(normalised[name].null_count()) - null_count)
        total_missing += null_count + unreadable
        if unreadable:
            unreadable_columns[name] = unreadable

        kind = _classify(
            series,
            parsed,
            None if numeric_parse is None else numeric_parse.values,
            distinct_count=distinct_count,
        )
        if name in normalised:
            series = normalised[name]
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
            distinct_count=distinct_count,
            min_value=min_value,
            max_value=max_value,
            mean_value=mean_value,
            sample_values=[_stringify(v) for v in non_null.head(5).to_list()],
            unreadable_count=unreadable,
        )

        if date_parse is not None:
            profile.parsed_as = date_parse.layout
            profile.order_ambiguous = date_parse.ambiguous
        elif numeric_parse is not None and numeric_parse.style != "plain":
            profile.parsed_as = numeric_parse.style

        _score_column(profile, frame.height)
        profiles.append(profile)

    guessed_target = _assign_roles(profiles)

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

    target_column = next((p for p in profiles if p.role is ColumnRole.TARGET), None)
    if target_column is not None:
        for column in _mixed_measures(
            frame,
            target_column.name,
            [p.name for p in profiles if p.kind is ColumnKind.CATEGORICAL],
        ):
            warnings.append(
                f"'{column}' looks like it names different measures rather than slices of one — "
                f"the values in '{target_column.name}' are orders of magnitude apart across it. "
                f"Group the run by '{column}', or filter to a single measure first; totalling "
                "them would add quantities that do not belong together."
            )

    for column in ambiguous_dates:
        warnings.append(
            f"Every value in '{column}' fits both day/month and month/day order, so the "
            "data cannot say which it is. It has been read as day/month — check the date "
            "range below, and set the order explicitly if it is wrong."
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

    if guessed_target:
        chosen = next((p.name for p in profiles if p.role is ColumnRole.TARGET), None)
        warnings.append(
            f"No column read as something a business forecasts, so '{chosen}' was used as the "
            "target because it is the only number here. Check that is what you meant."
        )

    for column, count in sorted(unreadable_columns.items(), key=lambda item: -item[1])[:3]:
        share = count / frame.height * 100.0 if frame.height else 0.0
        warnings.append(
            f"{count} value(s) in '{column}' ({share:.0f}%) were present but could not be "
            "read in the format the rest of the column is in, and are stored as blank."
        )

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
        normalised=frame.with_columns(**normalised) if normalised else frame,
    )


DATE_CANDIDATE_FLOOR = 0.5
TARGET_CANDIDATE_FLOOR = 0.4


def _score_column(profile: ColumnProfile, row_count: int) -> None:
    reasons: list[str] = []

    if profile.kind is ColumnKind.DATE:
        score = 0.6
        reasons.append("parses as dates")

        name_signal = name_score(profile.name, DATE_NAME_HINTS)
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
        profile.is_date_candidate = profile.date_score >= DATE_CANDIDATE_FLOOR

    if profile.kind is ColumnKind.NUMERIC:
        score = 0.40
        reasons.append("numeric")

        strong = name_score(profile.name, STRONG_TARGET_HINTS)
        weak = name_score(profile.name, WEAK_TARGET_HINTS)

        if strong:
            score += 0.40 * strong
            reasons.append("name states what is being measured")
        elif weak:
            score += 0.18 * weak
            reasons.append("name hints at a measure")

        if is_currency_like(profile.name):
            score += 0.08
            reasons.append("reads as money")

        if name_score(profile.name, WEIGHT_NAME_HINTS) >= 1.0 and not strong:
            score -= 0.12
            reasons.append("more likely a weight than a target")

        if (
            row_count
            and profile.distinct_count / row_count > 0.98
            and name_score(profile.name, ("id", "key", "index", "row", "number", "code"))
        ):
            score -= 0.5
            reasons.append("looks like an identifier")

        if profile.distinct_count <= 1:
            score -= 0.4
            reasons.append("constant value")

        if row_count and profile.null_count / row_count > 0.3:
            score -= 0.2
            reasons.append("sparsely populated")

        if row_count and profile.distinct_count > 1:
            score += 0.02 * min(1.0, profile.distinct_count / max(row_count, 1) * 4)

        profile.target_score = max(0.0, min(1.0, score))
        profile.is_target_candidate = profile.target_score >= TARGET_CANDIDATE_FLOOR

    profile.reason = ", ".join(reasons) if reasons else "no strong signal"


def _mixed_measures(frame: pl.DataFrame, target: str, candidates: list[str]) -> list[str]:
    if target not in frame.columns:
        return []

    values = frame[target]
    if not values.dtype.is_numeric():
        return []

    flagged: list[str] = []
    for name in candidates:
        if name not in frame.columns:
            continue
        if name_score(name, MEASURE_NAME_HINTS) >= 1.0:
            flagged.append(name)
            continue

        labels = frame[name]
        if not 2 <= labels.n_unique() <= MAX_MEASURE_LABELS:
            continue

        try:
            grouped = (
                frame.select(pl.col(name), pl.col(target).abs().alias("_magnitude"))
                .drop_nulls()
                .group_by(name)
                .agg(pl.col("_magnitude").median())
            )
        except Exception:
            continue

        medians = [float(v) for v in grouped["_magnitude"].drop_nulls() if float(v) > 0]
        if len(medians) < 2:
            continue
        if max(medians) / min(medians) >= MIXED_MEASURE_RATIO:
            flagged.append(name)

    return flagged


def _assign_roles(profiles: list[ColumnProfile]) -> bool:
    dates = sorted(
        (p for p in profiles if p.is_date_candidate), key=lambda p: p.date_score, reverse=True
    )
    targets = sorted(
        (p for p in profiles if p.is_target_candidate), key=lambda p: p.target_score, reverse=True
    )

    if dates:
        dates[0].role = ColumnRole.TIME

    fell_back = False
    if not targets:
        targets = sorted(
            (p for p in profiles if p.kind is ColumnKind.NUMERIC and p.role is ColumnRole.IGNORED),
            key=lambda p: p.target_score,
            reverse=True,
        )
        fell_back = bool(targets)

    if targets:
        targets[0].role = ColumnRole.TARGET
        if fell_back:
            targets[0].reason = (
                f"{targets[0].reason} No column scored as a forecast target, so the only "
                "numeric column left was used — check this is what you meant to forecast."
            ).strip()

    for profile in profiles:
        if profile.role is not ColumnRole.IGNORED:
            continue
        if profile.kind is ColumnKind.CATEGORICAL:
            if profile.distinct_count <= MAX_AUTO_DIMENSION_VALUES:
                profile.role = ColumnRole.DIMENSION
        elif profile.kind is ColumnKind.NUMERIC:
            profile.role = (
                ColumnRole.WEIGHT
                if name_score(profile.name, WEIGHT_NAME_HINTS) >= 1.0
                else ColumnRole.MEASURE
            )

    return fell_back


def suggestions(
    profiles: list[ColumnProfile], role: str
) -> list[tuple[str, ColumnKind, float, str]]:
    if role == "time":
        pool = [(p, p.date_score) for p in profiles if p.is_date_candidate]
    elif role == "target":
        pool = [(p, p.target_score) for p in profiles if p.is_target_candidate]
    else:
        pool = [
            (p, 0.6 + 0.4 * name_score(p.name, DIMENSION_NAME_HINTS))
            for p in profiles
            if p.kind is ColumnKind.CATEGORICAL
        ]

    pool.sort(key=lambda item: item[1], reverse=True)
    return [(p.name, p.kind, round(score, 3), p.reason) for p, score in pool]
