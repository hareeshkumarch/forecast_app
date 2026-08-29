from __future__ import annotations

from collections.abc import Iterable
from typing import cast

import polars as pl

from app.datasets.profiler import DatasetProfileResult, natural_aggregation, profile_frame
from app.models.enums import ForecastFrequency, MeasureAggregation
from app.schema.contract import (
    CONFIDENCE_FLOOR,
    MIN_MARGIN,
    ROLE_COVARIATE,
    ROLE_DATE,
    ROLE_DIMENSION,
    ROLE_TARGET,
    SOURCE_INFERRED,
    SOURCE_OVERRIDE,
    SOURCE_REMEMBERED,
    MappingProposal,
    MappingWarning,
    RoleCandidate,
    schema_fingerprint,
)
from app.schema.keys import resolve_keys
from app.schema.layout import LayoutResult, normalise_layout
from app.schema.roles import rank_roles

MAX_COVARIATES = 8


def fingerprint_of(frame: pl.DataFrame) -> str:
    return schema_fingerprint([(name, str(dtype)) for name, dtype in frame.schema.items()])


def prepare(
    frame: pl.DataFrame, *, day_first: bool | None = None
) -> tuple[pl.DataFrame, DatasetProfileResult, LayoutResult]:
    layout = normalise_layout(frame)
    profiled = profile_frame(layout.frame, day_first=day_first)
    working = profiled.normalised if profiled.normalised is not None else layout.frame
    return working, profiled, layout


def propose(
    frame: pl.DataFrame,
    *,
    day_first: bool | None = None,
    remembered: dict[str, object] | None = None,
    overrides: dict[str, object] | None = None,
) -> tuple[MappingProposal, pl.DataFrame]:
    fingerprint = fingerprint_of(frame)
    working, profiled, layout = prepare(frame, day_first=day_first)
    candidates = rank_roles(working, profiled.columns)

    warnings = list(layout.warnings)
    date_col = _best(candidates[ROLE_DATE])
    target_col = _best(candidates[ROLE_TARGET])

    if date_col is None:
        warnings.append(
            MappingWarning(
                code="no_date_column",
                message="No column in this file parses as dates, so no series can be built from it.",
            )
        )
    if target_col is None:
        warnings.append(
            MappingWarning(
                code="no_target_column",
                message="No column in this file reads as a number to forecast.",
            )
        )

    for role in (ROLE_DATE, ROLE_TARGET):
        contested = _contested(candidates[role])
        if contested is not None:
            warnings.append(contested)

    keys = (
        resolve_keys(working, date_col, [c.column for c in candidates[ROLE_DIMENSION]])
        if date_col is not None
        else None
    )
    series_keys = list(keys.series_keys) if keys else []

    if keys is not None and keys.needs_aggregation:
        warnings.append(
            MappingWarning(
                code="duplicate_grain",
                message=(
                    f"{keys.duplicate_rows} row(s) still share a period after every dimension "
                    "column is used as a key. Choose how to combine them — sum, mean or last — "
                    "or fix the file."
                ),
                columns=tuple(series_keys),
            )
        )

    covariates = [
        candidate.column
        for candidate in candidates[ROLE_COVARIATE]
        if candidate.column not in {target_col, date_col, *series_keys}
    ][:MAX_COVARIATES]

    proposal = MappingProposal(
        date_col=date_col,
        target_col=target_col,
        series_keys=series_keys,
        covariates=covariates,
        frequency=profiled.detected_frequency,
        aggregation=natural_aggregation(target_col) if target_col else None,
        confidence=_confidence(candidates, keys.duplicate_rows if keys else 0),
        warnings=warnings,
        fingerprint=fingerprint,
        layout=layout.layout,
        hierarchy=list(keys.hierarchy) if keys else [],
        candidates=candidates,
        source=SOURCE_INFERRED,
        requires_aggregation_choice=bool(keys and keys.needs_aggregation),
        series_count=keys.series_count if keys else 1,
    )

    if profiled.detected_frequency is None:
        proposal.frequency = ForecastFrequency.MONTHLY
        proposal.warnings.append(
            MappingWarning(
                code="frequency_not_inferred",
                message=(
                    "The gaps between periods are not regular, so the frequency could not be "
                    "read from the file. Monthly is proposed — confirm or change it."
                ),
                columns=(date_col,) if date_col else (),
            )
        )
        proposal.confidence = min(proposal.confidence, CONFIDENCE_FLOOR - 0.01)

    if remembered:
        apply_override(proposal, remembered, source=SOURCE_REMEMBERED)
    if overrides:
        apply_override(proposal, overrides, source=SOURCE_OVERRIDE)

    return proposal, working


def apply_override(
    proposal: MappingProposal, override: dict[str, object], *, source: str = SOURCE_OVERRIDE
) -> MappingProposal:
    if value := override.get("date_col"):
        proposal.date_col = str(value)
    if value := override.get("target_col"):
        proposal.target_col = str(value)
    # The override is a decoded JSON body, so every value arrives as `object`
    # and each field is coerced to the shape it is meant to have. A value of
    # the wrong shape raises here, which is the same answer as before.
    if (keys := override.get("series_keys")) is not None:
        proposal.series_keys = [str(key) for key in cast("Iterable[object]", keys)]
    if (covariates := override.get("covariates")) is not None:
        proposal.covariates = [str(name) for name in cast("Iterable[object]", covariates)]
    if value := override.get("frequency"):
        proposal.frequency = ForecastFrequency(str(value))
    if value := override.get("aggregation"):
        proposal.aggregation = MeasureAggregation(str(value))
        proposal.requires_aggregation_choice = False

    proposal.source = source
    proposal.confidence = 1.0 if proposal.complete else proposal.confidence
    return proposal


def _best(candidates: list[RoleCandidate]) -> str | None:
    return candidates[0].column if candidates else None


def _contested(candidates: list[RoleCandidate]) -> MappingWarning | None:
    if len(candidates) < 2:
        return None
    best, runner_up = candidates[0], candidates[1]
    if best.confidence - runner_up.confidence >= MIN_MARGIN:
        return None
    return MappingWarning(
        code=f"contested_{best.role}",
        message=(
            f"'{best.column}' scored {best.confidence:.2f} and '{runner_up.column}' scored "
            f"{runner_up.confidence:.2f} for the {best.role} column — too close to choose "
            "between them without being told."
        ),
        columns=(best.column, runner_up.column),
    )


def _confidence(candidates: dict[str, list[RoleCandidate]], duplicate_rows: int) -> float:
    scores = []
    for role in (ROLE_DATE, ROLE_TARGET):
        ranked = candidates[role]
        if not ranked:
            return 0.0
        margin = ranked[0].confidence - (ranked[1].confidence if len(ranked) > 1 else 0.0)
        scores.append(ranked[0].confidence * (1.0 if margin >= MIN_MARGIN else 0.85))

    confidence = min(scores)
    return round(confidence * (0.8 if duplicate_rows else 1.0), 3)
