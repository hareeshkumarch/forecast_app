from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations, pairwise

import polars as pl

MAX_KEY_CANDIDATES = 6
MAX_KEY_WIDTH = 4


@dataclass(slots=True)
class KeyResolution:
    series_keys: list[str] = field(default_factory=list)
    hierarchy: list[str] = field(default_factory=list)
    duplicate_rows: int = 0
    series_count: int = 1
    considered: list[str] = field(default_factory=list)

    @property
    def needs_aggregation(self) -> bool:
        return self.duplicate_rows > 0


def resolve_keys(frame: pl.DataFrame, date_column: str, dimensions: list[str]) -> KeyResolution:
    if date_column not in frame.columns:
        return KeyResolution()

    considered = [name for name in dimensions if name in frame.columns][:MAX_KEY_CANDIDATES]

    if _duplicate_rows(frame, [date_column]) == 0:
        return KeyResolution(
            series_keys=[],
            duplicate_rows=0,
            series_count=1,
            considered=considered,
        )

    best: tuple[str, ...] | None = None
    for width in range(1, min(MAX_KEY_WIDTH, len(considered)) + 1):
        exact = [
            subset
            for subset in combinations(considered, width)
            if _duplicate_rows(frame, [date_column, *subset]) == 0
        ]
        if exact:
            best = min(exact, key=lambda subset: (_series_count(frame, subset), subset))
            break

    if best is None:
        best = tuple(considered)

    keys = list(best)
    lineage = _lineage(frame, keys, considered)

    return KeyResolution(
        series_keys=lineage or keys,
        hierarchy=lineage,
        duplicate_rows=_duplicate_rows(frame, [date_column, *keys]),
        series_count=_series_count(frame, best) if keys else 1,
        considered=considered,
    )


def _lineage(frame: pl.DataFrame, keys: list[str], considered: list[str]) -> list[str]:
    if not keys:
        return []
    ancestors = [
        name for name in considered if name not in keys and _determined_by(frame, keys, name)
    ]
    return detect_hierarchy(frame, [*ancestors, *keys])


def _determined_by(frame: pl.DataFrame, keys: list[str], column: str) -> bool:
    fanned = frame.group_by(keys).agg(pl.col(column).n_unique().alias("values"))
    return fanned.height > 0 and bool((fanned["values"] <= 1).all())


def detect_hierarchy(frame: pl.DataFrame, keys: list[str]) -> list[str]:
    if len(keys) < 2:
        return []

    ordered = sorted(keys, key=lambda name: (frame[name].n_unique(), name))
    for parent, child in pairwise(ordered):
        if not _contains(frame, parent=parent, child=child):
            return []
    return ordered


def _contains(frame: pl.DataFrame, *, parent: str, child: str) -> bool:
    fanned = frame.group_by(child).agg(pl.col(parent).n_unique().alias("parents"))
    if fanned.height == 0:
        return False
    return bool((fanned["parents"] <= 1).all())


def _duplicate_rows(frame: pl.DataFrame, keys: list[str]) -> int:
    counted = frame.group_by(keys).len()
    return int(
        counted.filter(pl.col("len") > 1)["len"].sum() - counted.filter(pl.col("len") > 1).height
    )


def _series_count(frame: pl.DataFrame, keys: tuple[str, ...]) -> int:
    if not keys:
        return 1
    return int(frame.select(list(keys)).unique().height)
