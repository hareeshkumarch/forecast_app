from __future__ import annotations

import re
from dataclasses import dataclass, field

MIN_SIMILARITY = 0.6

MAX_CONSIDERED = 500

_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

EXACT = "exact"
RENAMED_TYPES = "same_columns"
SIMILAR = "similar_columns"


def normalise(name: str) -> str:
    return _NOT_ALPHANUMERIC.sub("_", name.strip().lower()).strip("_")


@dataclass(frozen=True, slots=True)
class Recall:
    fields: dict[str, object]
    kind: str
    similarity: float
    missing: tuple[str, ...] = ()

    @property
    def exact(self) -> bool:
        return self.kind == EXACT

    @property
    def same_columns(self) -> bool:
        return self.kind == RENAMED_TYPES


@dataclass(slots=True)
class StoredMapping:
    fingerprint: str
    date_col: str
    target_col: str
    series_keys: list[str] = field(default_factory=list)
    covariates: list[str] = field(default_factory=list)
    frequency: object | None = None
    aggregation: object | None = None
    columns: dict[str, str] = field(default_factory=dict)


def similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def recall(
    stored: list[StoredMapping],
    *,
    fingerprint: str,
    columns: dict[str, str],
) -> Recall | None:
    if not stored:
        return None

    present = {normalise(name) for name in columns}
    by_name = {normalise(name): name for name in columns}

    best: Recall | None = None
    for candidate in stored[:MAX_CONSIDERED]:
        if candidate.fingerprint == fingerprint:
            carried = _carry(candidate, by_name)
            if carried is not None:
                return Recall(carried[0], EXACT, 1.0, carried[1])
            continue

        stored_names = {normalise(name) for name in candidate.columns}
        score = similarity(present, stored_names)
        if score < MIN_SIMILARITY:
            continue

        carried = _carry(candidate, by_name)
        if carried is None:
            continue

        if best is None or score > best.similarity:
            kind = RENAMED_TYPES if stored_names == present else SIMILAR
            best = Recall(carried[0], kind, round(score, 3), carried[1])

    return best


def _carry(
    candidate: StoredMapping, by_name: dict[str, str]
) -> tuple[dict[str, object], tuple[str, ...]] | None:
    date_col = by_name.get(normalise(candidate.date_col))
    target_col = by_name.get(normalise(candidate.target_col))
    if date_col is None or target_col is None:
        return None

    missing: list[str] = []
    keys: list[str] = []
    for name in candidate.series_keys or []:
        found = by_name.get(normalise(name))
        (keys if found else missing).append(found or name)

    covariates: list[str] = []
    for name in candidate.covariates or []:
        found = by_name.get(normalise(name))
        if found:
            covariates.append(found)
        else:
            missing.append(name)

    fields: dict[str, object] = {
        "date_col": date_col,
        "target_col": target_col,
        "series_keys": keys,
        "covariates": covariates,
    }
    if candidate.frequency is not None:
        fields["frequency"] = candidate.frequency
    if candidate.aggregation is not None:
        fields["aggregation"] = candidate.aggregation

    return fields, tuple(missing)
