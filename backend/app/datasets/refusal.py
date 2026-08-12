from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

import polars as pl

from app.datasets.profiler import (
    DATE_CANDIDATE_FLOOR,
    TARGET_CANDIDATE_FLOOR,
    ColumnProfile,
    DatasetProfileResult,
)
from app.forecasting.frequency import seasonal_period
from app.models.enums import ColumnKind, ForecastFrequency

MIN_DATE_CONFIDENCE = DATE_CANDIDATE_FLOOR
MIN_TARGET_CONFIDENCE = TARGET_CANDIDATE_FLOOR

MIN_MARGIN = 0.12

EVIDENCE_ROWS = 5

REQUIRED_SEASONS = 2


class Verdict(StrEnum):
    PROCEED = "proceed"
    CONFIRM = "confirm"
    REFUSE = "refuse"


@dataclass(slots=True, frozen=True)
class Question:

    code: str
    column: str | None
    question: str
    options: tuple[str, ...]
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "column": self.column,
            "question": self.question,
            "options": list(self.options),
            "evidence": list(self.evidence),
        }


@dataclass(slots=True, frozen=True)
class Quarantine:

    code: str
    reason: str
    count: int
    examples: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "reason": self.reason,
            "count": self.count,
            "examples": list(self.examples),
        }


@dataclass(slots=True, frozen=True)
class ColumnChoice:

    role: str
    chosen: str | None
    confidence: float
    runner_up: str | None
    runner_up_confidence: float
    plausible: bool = True

    @property
    def margin(self) -> float:
        return self.confidence - self.runner_up_confidence

    @property
    def confident(self) -> bool:
        if self.chosen is None or not self.plausible:
            return False
        return self.runner_up is None or self.margin >= MIN_MARGIN

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "chosen": self.chosen,
            "confidence": round(self.confidence, 3),
            "runner_up": self.runner_up,
            "runner_up_confidence": round(self.runner_up_confidence, 3),
            "margin": round(self.margin, 3),
            "plausible": self.plausible,
            "confident": self.confident,
        }


@dataclass(slots=True)
class SeriesGate:

    label: str
    observations: int
    required: int
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "series": self.label,
            "observations": self.observations,
            "required": self.required,
            "reason": self.reason,
        }


@dataclass(slots=True)
class IngestVerdict:
    verdict: Verdict
    choices: list[ColumnChoice] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    quarantined: list[Quarantine] = field(default_factory=list)
    gated_series: list[SeriesGate] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def rows_quarantined(self) -> int:
        return sum(item.count for item in self.quarantined)

    def as_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "columns": [choice.as_dict() for choice in self.choices],
            "questions": [question.as_dict() for question in self.questions],
            "quarantined": [item.as_dict() for item in self.quarantined],
            "rows_quarantined": self.rows_quarantined,
            "gated_series": [gate.as_dict() for gate in self.gated_series],
            "refusals": list(self.refusals),
        }


def _ranked(profiles: Sequence[ColumnProfile], role: str) -> list[tuple[ColumnProfile, float]]:
    if role == "time":
        pool = [(p, p.date_score) for p in profiles if p.kind is ColumnKind.DATE]
    else:
        pool = [(p, p.target_score) for p in profiles if p.kind is ColumnKind.NUMERIC]
    return sorted(pool, key=lambda item: item[1], reverse=True)


def _choice(profiles: Sequence[ColumnProfile], role: str) -> ColumnChoice:
    ranked = _ranked(profiles, role)
    best = ranked[0] if ranked else None
    second = ranked[1] if len(ranked) > 1 else None
    floor = MIN_DATE_CONFIDENCE if role == "time" else MIN_TARGET_CONFIDENCE
    return ColumnChoice(
        role=role,
        chosen=best[0].name if best else None,
        confidence=best[1] if best else 0.0,
        runner_up=second[0].name if second else None,
        runner_up_confidence=second[1] if second else 0.0,
        plausible=best is not None and best[1] >= floor,
    )


def _conflicting_dates(frame: pl.DataFrame | None, column: str | None) -> tuple[str, ...]:
    if frame is None or column is None or column not in frame.columns:
        return ()

    text = frame[column].cast(pl.Utf8, strict=False).drop_nulls()
    examples: list[str] = []
    for raw in text.head(2000).to_list():
        token = str(raw)
        parts = token.replace("-", "/").replace(".", "/").split("/")
        if len(parts) < 2:
            continue
        head, tail = parts[0].strip(), parts[1].strip()
        if not (head.isdigit() and tail.isdigit()):
            continue
        first, second = int(head), int(tail)
        if first == second or first > 12 or second > 12:
            continue
        examples.append(token)
        if len(examples) >= EVIDENCE_ROWS:
            break
    return tuple(examples)


def _unreadable(profiles: Sequence[ColumnProfile], role_column: str | None) -> Quarantine | None:
    if role_column is None:
        return None
    profile = next((p for p in profiles if p.name == role_column), None)
    if profile is None or profile.unreadable_count == 0:
        return None
    return Quarantine(
        code="unreadable_values",
        reason=(
            f"{profile.unreadable_count} value(s) in '{profile.name}' could not be read as "
            f"{profile.kind.value}. They are set aside, not treated as zero or as missing."
        ),
        count=profile.unreadable_count,
        examples=tuple(str(v) for v in profile.sample_values[:EVIDENCE_ROWS]),
    )


def duplicate_keys(
    frame: pl.DataFrame,
    time_column: str,
    dimensions: Sequence[str] = (),
) -> tuple[int, tuple[str, ...]]:
    keys = [time_column, *[d for d in dimensions if d in frame.columns]]
    if time_column not in frame.columns:
        return 0, ()

    counts = frame.group_by(keys).len().filter(pl.col("len") > 1)
    if counts.height == 0:
        return 0, ()

    repeated = int(counts["len"].sum() - counts.height)
    examples = tuple(
        " / ".join(f"{key}={row[key]}" for key in keys) + f" x{row['len']}"
        for row in counts.head(EVIDENCE_ROWS).to_dicts()
    )
    return repeated, examples


def history_gate(
    series_lengths: dict[str, int],
    frequency: ForecastFrequency,
) -> list[SeriesGate]:
    period = seasonal_period(frequency)
    required = max(REQUIRED_SEASONS * period, 4) if period > 1 else 6

    return [
        SeriesGate(
            label=label,
            observations=length,
            required=required,
            reason=(
                f"{length} period(s) of history against the {required} that "
                f"{REQUIRED_SEASONS} seasonal cycles at this frequency need. "
                "Routed to a baseline instead of a fitted model."
            ),
        )
        for label, length in sorted(series_lengths.items())
        if length < required
    ]


def assess(
    profile: DatasetProfileResult,
    *,
    frame: pl.DataFrame | None = None,
    dimensions: Sequence[str] = (),
    series_lengths: dict[str, int] | None = None,
) -> IngestVerdict:
    profiles = profile.columns
    time_choice = _choice(profiles, "time")
    target_choice = _choice(profiles, "target")

    verdict = IngestVerdict(verdict=Verdict.PROCEED, choices=[time_choice, target_choice])

    if len(profiles) < 2:
        verdict.refusals.append(
            f"This file has {len(profiles)} column(s). A forecast needs at least a column of "
            "dates and a column of numbers."
        )
    if time_choice.chosen is None:
        verdict.refusals.append(
            "No column in this file reads as dates. Check the date column is not stored as "
            "text in a format we do not recognise, and that the header row is the first row."
        )
    if target_choice.chosen is None:
        verdict.refusals.append(
            "No column in this file reads as numbers to forecast. A quantity or value column "
            "is required."
        )
    if profile.row_count == 0:
        verdict.refusals.append("This file has a header but no rows under it.")

    if verdict.refusals:
        verdict.verdict = Verdict.REFUSE
        return verdict

    for choice in (time_choice, target_choice):
        if choice.confident:
            continue
        alternatives = tuple(p.name for p, _ in _ranked(profiles, choice.role)[:4])
        verdict.questions.append(
            Question(
                code=f"low_confidence_{choice.role}",
                column=choice.chosen,
                question=(
                    f"Which column holds the {'date' if choice.role == 'time' else 'value to forecast'}? "
                    f"'{choice.chosen}' scored {choice.confidence:.2f}"
                    + (
                        f", and '{choice.runner_up}' scored {choice.runner_up_confidence:.2f} — "
                        "too close to choose between them."
                        if choice.plausible
                        else ", which is below the score at which a column reads as that role."
                    )
                ),
                options=alternatives,
            )
        )

    chosen_time = next((p for p in profiles if p.name == time_choice.chosen), None)
    if chosen_time is not None and chosen_time.order_ambiguous:
        verdict.questions.append(
            Question(
                code="ambiguous_date_order",
                column=chosen_time.name,
                question=(
                    f"Every date in '{chosen_time.name}' fits both day/month and month/day, so "
                    "the order cannot be read from the file. Which is it?"
                ),
                options=("day/month (15/01/2024 is 15 January)", "month/day (01/15/2024 is 15 January)"),
                evidence=_conflicting_dates(frame, chosen_time.name),
            )
        )

    if frame is not None and time_choice.chosen is not None:
        repeated, examples = duplicate_keys(frame, time_choice.chosen, dimensions)
        if repeated:
            verdict.questions.append(
                Question(
                    code="duplicate_keys",
                    column=time_choice.chosen,
                    question=(
                        f"{repeated} row(s) share a period with another row at the same grain. "
                        "Add them together, or is this file a join that duplicated rows?"
                    ),
                    options=("add them together", "take the mean", "stop and let me fix the file"),
                    evidence=examples,
                )
            )

    if profile.detected_frequency is None:
        verdict.questions.append(
            Question(
                code="irregular_spacing",
                column=time_choice.chosen,
                question=(
                    "The gaps between periods in this file are not regular, so the frequency "
                    "could not be detected. Which should it be forecast at?"
                ),
                options=("daily", "weekly", "monthly", "quarterly"),
            )
        )

    for column in (time_choice.chosen, target_choice.chosen):
        held = _unreadable(profiles, column)
        if held is not None:
            verdict.quarantined.append(held)

    if series_lengths and profile.detected_frequency is not None:
        verdict.gated_series = history_gate(series_lengths, profile.detected_frequency)

    if verdict.questions:
        verdict.verdict = Verdict.CONFIRM
    return verdict


def series_lengths_from(
    frame: pl.DataFrame,
    time_column: str,
    dimensions: Sequence[str] = (),
) -> dict[str, int]:
    if time_column not in frame.columns:
        return {}

    group = [d for d in dimensions if d in frame.columns]
    if not group:
        return {"the total": int(frame[time_column].n_unique())}

    counted = frame.group_by(group).agg(pl.col(time_column).n_unique().alias("periods"))
    return {
        " / ".join(str(row[key]) for key in group): int(row["periods"])
        for row in counted.to_dicts()
    }


def earliest_and_latest(frame: pl.DataFrame, column: str) -> tuple[date | None, date | None]:
    if column not in frame.columns:
        return None, None
    parsed = frame[column].cast(pl.Date, strict=False).drop_nulls()
    if parsed.len() == 0:
        return None, None
    return parsed.min(), parsed.max()  # type: ignore[return-value]
