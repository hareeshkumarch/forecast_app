from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.models.enums import ForecastFrequency, MeasureAggregation

DS = "ds"
Y = "y"
SERIES_ID = "series_id"
CANONICAL_COLUMNS = (SERIES_ID, DS, Y)

SINGLE_SERIES_ID = "total"
SERIES_KEY_SEPARATOR = " · "

LAYOUT_LONG = "long"
LAYOUT_WIDE = "wide"

SOURCE_INFERRED = "inferred"
SOURCE_REMEMBERED = "remembered"
SOURCE_OVERRIDE = "override"

ROLE_DATE = "date"
ROLE_TARGET = "target"
ROLE_DIMENSION = "dimension"
ROLE_COVARIATE = "covariate"
ROLE_IGNORE = "ignore"

#: Below this a proposal is put to the user rather than acted on. It is the
#: floor the refusal layer already uses for a target column, so one file cannot
#: be confident enough to run and not confident enough to ingest.
CONFIDENCE_FLOOR = 0.55

#: How far ahead of the runner-up a column has to score before the choice is
#: made without asking.
MIN_MARGIN = 0.12

#: Warnings that stand in the way of running. A high score on a column that a
#: second column matches is still a guess, and a guess about what is being
#: forecast is not one to make silently.
BLOCKING_WARNINGS = frozenset(
    {
        "contested_date",
        "contested_target",
        "duplicate_grain",
        "no_date_column",
        "no_target_column",
        "frequency_not_inferred",
    }
)


@dataclass(slots=True, frozen=True)
class RoleCandidate:
    column: str
    role: str
    confidence: float
    evidence: str

    def as_dict(self) -> dict[str, object]:
        return {
            "column": self.column,
            "role": self.role,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
        }


@dataclass(slots=True, frozen=True)
class MappingWarning:
    code: str
    message: str
    columns: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "columns": list(self.columns)}


@dataclass(slots=True)
class MappingProposal:
    date_col: str | None
    target_col: str | None
    series_keys: list[str] = field(default_factory=list)
    covariates: list[str] = field(default_factory=list)
    frequency: ForecastFrequency | None = None
    aggregation: MeasureAggregation | None = None
    confidence: float = 0.0
    warnings: list[MappingWarning] = field(default_factory=list)

    fingerprint: str = ""
    layout: str = LAYOUT_LONG
    hierarchy: list[str] = field(default_factory=list)
    candidates: dict[str, list[RoleCandidate]] = field(default_factory=dict)
    source: str = SOURCE_INFERRED
    requires_aggregation_choice: bool = False
    series_count: int = 0

    @property
    def complete(self) -> bool:
        return self.date_col is not None and self.target_col is not None

    @property
    def needs_confirmation(self) -> bool:
        if not self.complete or self.requires_aggregation_choice:
            return True
        if self.source in (SOURCE_REMEMBERED, SOURCE_OVERRIDE):
            return False
        if any(warning.code in BLOCKING_WARNINGS for warning in self.warnings):
            return True
        return self.confidence < CONFIDENCE_FLOOR

    def as_dict(self) -> dict[str, object]:
        return {
            "date_col": self.date_col,
            "target_col": self.target_col,
            "series_keys": list(self.series_keys),
            "covariates": list(self.covariates),
            "frequency": self.frequency.value if self.frequency else None,
            "aggregation": self.aggregation.value if self.aggregation else None,
            "confidence": round(self.confidence, 3),
            "warnings": [warning.as_dict() for warning in self.warnings],
            "fingerprint": self.fingerprint,
            "layout": self.layout,
            "hierarchy": list(self.hierarchy),
            "candidates": {
                role: [candidate.as_dict() for candidate in ranked]
                for role, ranked in sorted(self.candidates.items())
            },
            "source": self.source,
            "requires_aggregation_choice": self.requires_aggregation_choice,
            "series_count": self.series_count,
            "needs_confirmation": self.needs_confirmation,
        }


def schema_fingerprint(columns: Sequence[tuple[str, str]]) -> str:
    payload = "\x1f".join(f"{name}\x1e{dtype}" for name, dtype in sorted(columns))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
