"""Finding the mapping somebody already made for a file like this one.

The memory was keyed on an exact fingerprint — every column name *and* every
dtype, hashed. That is the right fast path and the wrong only path, because
the case it exists for is the same export uploaded again next month, and that
file routinely is not identical:

  * one value in a column gains a decimal, so polars reads Int64 where it read
    Float64 last time, and the fingerprint changes;
  * the source system appends a column nobody asked for;
  * a column is renamed, or dropped because it was always empty.

Any of those and the mapping is silently not found. The person who carefully
told the platform which column was the target last month is asked again, with
nothing on screen explaining why. This finds the nearest stored mapping
instead, and is explicit about how near it was and what it could not carry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Below this, two files are not the same report and a remembered mapping is a
#: guess dressed as a memory. Two thirds of the columns in common, counted
#: against the union, is a column or two added or dropped — not a new file.
MIN_SIMILARITY = 0.6

#: Loaded per proposal and scored in Python. One row per distinct schema ever
#: accepted, so this is tens on a real deployment; the cap is to bound the day
#: somebody scripts a thousand uploads rather than because it is expected.
MAX_CONSIDERED = 500

_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

EXACT = "exact"
RENAMED_TYPES = "same_columns"
SIMILAR = "similar_columns"


def normalise(name: str) -> str:
    """`Net Revenue (USD)` and `net_revenue_usd` are the same column."""
    return _NOT_ALPHANUMERIC.sub("_", name.strip().lower()).strip("_")


@dataclass(frozen=True, slots=True)
class Recall:
    """A stored mapping, and how much of it survives the file in front of us."""

    fields: dict[str, object]
    kind: str
    similarity: float
    #: Columns the stored mapping named that this file does not have. Reported
    #: rather than silently dropped: "we remembered your mapping" is a
    #: different statement from "we remembered most of it".
    missing: tuple[str, ...] = ()

    @property
    def exact(self) -> bool:
        return self.kind == EXACT


@dataclass(slots=True)
class StoredMapping:
    """What `recall` needs from a row, so it can be tested without a database."""

    fingerprint: str
    date_col: str
    target_col: str
    series_keys: list[str] = field(default_factory=list)
    covariates: list[str] = field(default_factory=list)
    frequency: object | None = None
    aggregation: object | None = None
    columns: dict[str, str] = field(default_factory=dict)


def similarity(left: set[str], right: set[str]) -> float:
    """Jaccard over normalised column names.

    Over the union rather than over the smaller side, so a file whose columns
    are a subset of a much wider stored schema does not score 1.0 — the report
    that lost six of its ten columns is not the same report.
    """
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def recall(
    stored: list[StoredMapping],
    *,
    fingerprint: str,
    columns: dict[str, str],
) -> Recall | None:
    """The best stored mapping for this file, or None if none is close enough."""
    if not stored:
        return None

    present = {normalise(name) for name in columns}
    by_name = {normalise(name): name for name in columns}

    best: Recall | None = None
    for candidate in stored[:MAX_CONSIDERED]:
        if candidate.fingerprint == fingerprint:
            carried = _carry(candidate, present, by_name)
            if carried is not None:
                # Nothing beats an exact match, so stop looking.
                return Recall(carried[0], EXACT, 1.0, carried[1])
            continue

        stored_names = {normalise(name) for name in candidate.columns}
        score = similarity(present, stored_names)
        if score < MIN_SIMILARITY:
            continue

        carried = _carry(candidate, present, by_name)
        if carried is None:
            # The columns it names are gone. A mapping that points at a target
            # this file does not have is worse than no mapping at all.
            continue

        kind = RENAMED_TYPES if stored_names == present else SIMILAR
        if best is None or (score, kind == RENAMED_TYPES) > (
            best.similarity,
            best.kind == RENAMED_TYPES,
        ):
            best = Recall(carried[0], kind, round(score, 3), carried[1])

    return best


def _carry(
    candidate: StoredMapping, present: set[str], by_name: dict[str, str]
) -> tuple[dict[str, object], tuple[str, ...]] | None:
    """The parts of a stored mapping this file can still use.

    Columns are matched by normalised name and handed back under the *new*
    file's spelling, so a mapping stored against `Net Revenue` still applies to
    a file that calls it `net_revenue`.
    """
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

    del present
    return fields, tuple(missing)
