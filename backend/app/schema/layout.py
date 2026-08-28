from __future__ import annotations

import re
from dataclasses import dataclass, field

import polars as pl

from app.datasets.coercion import coerce_numeric, unpivot_periods
from app.schema.contract import LAYOUT_LONG, LAYOUT_WIDE, MappingWarning

MAX_HEADER_ROWS = 3

_PLACEHOLDER = re.compile(r"^(column_?\d*|unnamed[:_ ]?\d*|_duplicated_\d+|field_?\d+|\s*)$", re.I)
_NUMERIC = re.compile(r"^[\s+\-]?[\d.,]+\s*%?$")

PERIOD_COLUMN = "period"
VALUE_COLUMN = "value"


@dataclass(slots=True)
class LayoutResult:
    frame: pl.DataFrame
    layout: str
    period_columns: list[str] = field(default_factory=list)
    header_rows: int = 0
    warnings: list[MappingWarning] = field(default_factory=list)


def normalise_layout(frame: pl.DataFrame) -> LayoutResult:
    warnings: list[MappingWarning] = []

    frame, header_rows = _resolve_header(_drop_blank_leading_rows(frame))
    if header_rows:
        warnings.append(
            MappingWarning(
                code="header_promoted",
                message=(
                    f"The column names were read from row {header_rows} of the file; "
                    "the rows above it were titles or merged labels."
                ),
            )
        )

    reshaped = unpivot_periods(frame, period_name=PERIOD_COLUMN, value_name=VALUE_COLUMN)
    if reshaped is None:
        return LayoutResult(
            frame=frame, layout=LAYOUT_LONG, header_rows=header_rows, warnings=warnings
        )

    long, periods = reshaped
    warnings.append(
        MappingWarning(
            code="wide_layout_melted",
            message=(
                f"{len(periods)} date columns across the top of this file were turned into "
                f"rows under '{PERIOD_COLUMN}' and '{VALUE_COLUMN}'."
            ),
            columns=tuple(sorted(periods)),
        )
    )
    return LayoutResult(
        frame=long,
        layout=LAYOUT_WIDE,
        period_columns=sorted(periods),
        header_rows=header_rows,
        warnings=warnings,
    )


def _drop_blank_leading_rows(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.height == 0:
        return frame
    kept = frame.filter(pl.any_horizontal(pl.all().is_not_null()))
    return kept if kept.height else frame


def _resolve_header(frame: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    promoted = 0
    while promoted < MAX_HEADER_ROWS and frame.height > 1 and _header_unusable(frame):
        frame = _promote_row(frame)
        promoted += 1

    if promoted and frame.height > 1 and _split_across_two_rows(frame):
        frame = _promote_row(frame, combine=True)
        promoted += 1

    return (_restore_types(frame), promoted) if promoted else (frame, 0)


def _header_unusable(frame: pl.DataFrame) -> bool:
    placeholders = sum(1 for name in frame.columns if _PLACEHOLDER.match(name.strip()))
    return placeholders >= max(1, len(frame.columns) // 2)


def _split_across_two_rows(frame: pl.DataFrame) -> bool:
    names = frame.columns
    if len(set(names)) == len(names):
        return False
    return all(value is not None and not _looks_numeric(value) for value in frame.row(0))


def _promote_row(frame: pl.DataFrame, *, combine: bool = False) -> pl.DataFrame:
    labels = _forward_filled(frame.row(0))
    names: list[str] = []
    seen: dict[str, int] = {}

    for existing, label in zip(frame.columns, labels, strict=True):
        base = existing.strip()
        if label:
            base = f"{base} {label}".strip() if combine and not _PLACEHOLDER.match(base) else label
        base = base or "column"
        if base in seen:
            seen[base] += 1
            base = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
        names.append(base)

    return frame.slice(1).rename(dict(zip(frame.columns, names, strict=True)))


def _forward_filled(row: tuple[object, ...]) -> list[str]:
    labels: list[str] = []
    carried = ""
    for value in row:
        text = "" if value is None else str(value).strip()
        carried = text or carried
        labels.append(carried)
    return labels


def _looks_numeric(value: object) -> bool:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return True
    return bool(_NUMERIC.match(str(value).strip()))


def _restore_types(frame: pl.DataFrame) -> pl.DataFrame:
    converted = [
        parsed.values.rename(name)
        for name in frame.columns
        if frame[name].dtype == pl.Utf8 and (parsed := coerce_numeric(frame[name])) is not None
    ]
    return frame.with_columns(converted) if converted else frame
