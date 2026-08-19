from __future__ import annotations

import polars as pl

from app.datasets.profiler import (
    DIMENSION_NAME_HINTS,
    ColumnProfile,
    name_score,
)
from app.models.enums import ColumnKind
from app.schema.contract import (
    ROLE_COVARIATE,
    ROLE_DATE,
    ROLE_DIMENSION,
    ROLE_IGNORE,
    ROLE_TARGET,
    RoleCandidate,
)

NEAR_UNIQUE_SHARE = 0.9
MAX_DIMENSION_SHARE = 0.5
MIN_REPEAT_SHARE = 0.25


def rank_roles(
    frame: pl.DataFrame, profiles: list[ColumnProfile]
) -> dict[str, list[RoleCandidate]]:
    rows = max(1, frame.height)
    dates = _date_candidates(frame, profiles)
    targets = _target_candidates(profiles, rows)
    chosen_target = targets[0].column if targets else None
    anchor = dates[0].column if dates else None

    dimensions = _dimension_candidates(frame, profiles, rows, anchor)
    covariates = [
        RoleCandidate(
            column=profile.name,
            role=ROLE_COVARIATE,
            confidence=round(0.45 + 0.3 * profile.target_score, 3),
            evidence=f"numeric, not selected as the target ({profile.reason})",
        )
        for profile in profiles
        if profile.kind is ColumnKind.NUMERIC
        and profile.name != chosen_target
        and profile.distinct_count > 1
    ]

    return {
        ROLE_DATE: dates,
        ROLE_TARGET: targets,
        ROLE_DIMENSION: dimensions,
        ROLE_COVARIATE: _ranked(covariates),
        ROLE_IGNORE: _ignore_candidates(profiles, rows),
    }


def _date_candidates(frame: pl.DataFrame, profiles: list[ColumnProfile]) -> list[RoleCandidate]:
    candidates = []
    for profile in profiles:
        if profile.kind is not ColumnKind.DATE or not profile.is_date_candidate:
            continue
        ordering = _monotonic_share(frame, profile.name)
        confidence = min(1.0, profile.date_score + 0.1 * max(0.0, ordering - 0.5) * 2)
        candidates.append(
            RoleCandidate(
                column=profile.name,
                role=ROLE_DATE,
                confidence=round(confidence, 3),
                evidence=f"{profile.reason}; {ordering:.0%} of rows in ascending order",
            )
        )
    return _ranked(candidates)


def _target_candidates(profiles: list[ColumnProfile], rows: int) -> list[RoleCandidate]:
    candidates = []
    for profile in profiles:
        if profile.kind is not ColumnKind.NUMERIC or not profile.is_target_candidate:
            continue
        if profile.distinct_count <= 1:
            continue
        if profile.distinct_count / rows > NEAR_UNIQUE_SHARE and profile.null_count == 0:
            identifier = name_score(profile.name, ("id", "key", "code", "number", "index"))
            if identifier:
                continue
        candidates.append(
            RoleCandidate(
                column=profile.name,
                role=ROLE_TARGET,
                confidence=round(profile.target_score, 3),
                evidence=profile.reason,
            )
        )
    return _ranked(candidates)


def _dimension_candidates(
    frame: pl.DataFrame,
    profiles: list[ColumnProfile],
    rows: int,
    date_column: str | None,
) -> list[RoleCandidate]:
    candidates = []
    for profile in profiles:
        if profile.kind not in (ColumnKind.CATEGORICAL, ColumnKind.BOOLEAN):
            continue
        if profile.distinct_count <= 1 or profile.distinct_count >= rows:
            continue

        share = profile.distinct_count / rows
        if share > MAX_DIMENSION_SHARE:
            continue

        repeats = _repeat_share(frame, profile.name, date_column)
        confidence = (
            0.40
            + 0.20 * (1.0 - min(1.0, share / MAX_DIMENSION_SHARE))
            + 0.25 * repeats
            + 0.15 * name_score(profile.name, DIMENSION_NAME_HINTS)
        )
        candidates.append(
            RoleCandidate(
                column=profile.name,
                role=ROLE_DIMENSION,
                confidence=round(min(1.0, confidence), 3),
                evidence=(
                    f"{profile.distinct_count} distinct values over {rows} rows; "
                    f"{repeats:.0%} of them recur across dates"
                ),
            )
        )
    return _ranked(candidates)


def _ignore_candidates(profiles: list[ColumnProfile], rows: int) -> list[RoleCandidate]:
    candidates = []
    for profile in profiles:
        reason = None
        if profile.null_count >= rows:
            reason = "every value is empty"
        elif profile.distinct_count <= 1:
            reason = "one value throughout"
        elif profile.kind is ColumnKind.TEXT:
            share = profile.distinct_count / rows
            reason = (
                "near-unique free text"
                if share >= NEAR_UNIQUE_SHARE
                else "free text, not a category"
            )
        if reason is None:
            continue
        candidates.append(
            RoleCandidate(column=profile.name, role=ROLE_IGNORE, confidence=0.9, evidence=reason)
        )
    return _ranked(candidates)


def _monotonic_share(frame: pl.DataFrame, column: str) -> float:
    values = frame[column].cast(pl.Date, strict=False).cast(pl.Int64, strict=False).drop_nulls()
    if values.len() < 2:
        return 1.0
    steps = values.diff().drop_nulls()
    if steps.len() == 0:
        return 1.0
    return float((steps >= 0).sum()) / steps.len()


def _repeat_share(frame: pl.DataFrame, column: str, date_column: str | None) -> float:
    if date_column is None or date_column not in frame.columns:
        counts = frame[column].value_counts()
        repeated = int((counts["count"] > 1).sum())
        return repeated / max(1, counts.height)

    grouped = frame.group_by(column).agg(pl.col(date_column).n_unique().alias("dates"))
    if grouped.height == 0:
        return 0.0
    return float((grouped["dates"] > 1).sum()) / grouped.height


def _ranked(candidates: list[RoleCandidate]) -> list[RoleCandidate]:
    return sorted(candidates, key=lambda candidate: (-candidate.confidence, candidate.column))
