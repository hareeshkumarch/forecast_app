from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from app.forecasting.drivers import PERIOD_WORDS
from app.forecasting.metrics import intervals_held
from app.models.enums import ForecastFrequency

PLANNABLE_ACCURACY = 75.0
DIRECTIONAL_ACCURACY = 55.0
RELIABLE_BAND_SHARE = 0.6
DIRECTIONAL_SHARE = 0.5
CONCENTRATION_SHARE = 0.5
CONCENTRATION_LIFT = 2.0
MATERIAL_DOWNSIDE_PCT = 5.0


class Grade(StrEnum):
    PLANNABLE = "plannable"
    DIRECTIONAL = "directional"
    INDICATIVE = "indicative"


GRADE_MEANING: dict[Grade, str] = {
    Grade.PLANNABLE: "Period totals are firm enough to commit to.",
    Grade.DIRECTIONAL: "Read the shape and the totals; treat single periods as approximate.",
    Grade.INDICATIVE: "Direction only. Do not set targets from these numbers.",
}


@dataclass(frozen=True, slots=True)
class Action:
    headline: str
    detail: str
    urgency: int = 0


@dataclass(frozen=True, slots=True)
class Horizon:
    periods: int
    through: date | None
    covers_run: bool


@dataclass(frozen=True, slots=True)
class Concentration:
    count: int
    total: int
    share: float
    leaders: list[str] = field(default_factory=list)

    @property
    def lopsided(self) -> bool:
        if self.total <= 1 or self.count >= self.total:
            return False
        return self.share / 100.0 >= CONCENTRATION_LIFT * (self.count / self.total)


@dataclass(frozen=True, slots=True)
class Decision:
    grade: Grade
    accuracy: float | None
    confidence_level: float

    commit: float
    base: float
    prepare: float

    horizon: Horizon
    exposure: float
    downside_pct: float

    concentration: Concentration | None
    lean_pct: float | None
    actions: list[Action] = field(default_factory=list)

    @property
    def meaning(self) -> str:
        return GRADE_MEANING[self.grade]

    @property
    def spread_pct(self) -> float:
        return 0.0 if not self.base else abs(self.prepare - self.commit) / abs(self.base) * 100.0


@dataclass(frozen=True, slots=True)
class Period:
    period: date
    forecast: float
    lower: float | None
    upper: float | None
    worst: float | None = None


def grade_for(accuracy: float | None) -> Grade:
    if accuracy is None:
        return Grade.INDICATIVE
    if accuracy >= PLANNABLE_ACCURACY:
        return Grade.PLANNABLE
    if accuracy >= DIRECTIONAL_ACCURACY:
        return Grade.DIRECTIONAL
    return Grade.INDICATIVE


def reliable_horizon(periods: list[Period]) -> Horizon:
    reliable = 0
    for point in periods:
        if point.lower is None or point.upper is None:
            break
        scale = abs(point.forecast)
        if scale == 0.0:
            break
        if (point.upper - point.lower) / scale > RELIABLE_BAND_SHARE:
            break
        reliable += 1

    through = periods[reliable - 1].period if reliable else None
    return Horizon(periods=reliable, through=through, covers_run=reliable == len(periods))


def concentration_of(at_risk: list[tuple[str, float]]) -> Concentration | None:
    positive = sorted(
        ((label, value) for label, value in at_risk if value > 0),
        key=lambda row: row[1],
        reverse=True,
    )
    if not positive:
        return None

    total = sum(value for _, value in positive)
    if total <= 0:
        return None

    running = 0.0
    count = 0
    for _, value in positive:
        running += value
        count += 1
        if running / total >= CONCENTRATION_SHARE:
            break

    return Concentration(
        count=count,
        total=len(positive),
        share=running / total * 100.0,
        leaders=[label for label, _ in positive[: min(count, 3)]],
    )


def decide(
    periods: list[Period],
    *,
    frequency: ForecastFrequency,
    confidence_level: float,
    accuracy: float | None,
    at_risk: list[tuple[str, float]] | None = None,
    realized_bias: float | None = None,
    realized_wmape: float | None = None,
    realized_coverage: float | None = None,
) -> Decision | None:
    if not periods:
        return None

    base = sum(point.forecast for point in periods)
    bounded = [point for point in periods if point.lower is not None and point.upper is not None]
    commit = sum(point.lower or point.forecast for point in periods) if bounded else base
    prepare = sum(point.upper or point.forecast for point in periods) if bounded else base

    worst = [point.worst for point in periods if point.worst is not None]
    worst_total = sum(worst) if len(worst) == len(periods) else commit
    downside_pct = (base - worst_total) / abs(base) * 100.0 if base else 0.0

    grade = grade_for(accuracy)
    horizon = reliable_horizon(periods)
    concentration = concentration_of(at_risk or [])
    lean = _lean(realized_bias, realized_wmape)

    return Decision(
        grade=grade,
        accuracy=accuracy,
        confidence_level=confidence_level,
        commit=commit,
        base=base,
        prepare=prepare,
        horizon=horizon,
        exposure=base - worst_total,
        downside_pct=downside_pct,
        concentration=concentration,
        lean_pct=lean,
        actions=_actions(
            grade=grade,
            horizon=horizon,
            frequency=frequency,
            confidence_level=confidence_level,
            downside_pct=downside_pct,
            concentration=concentration,
            lean=lean,
            realized_coverage=realized_coverage,
            total=len(periods),
        ),
    )


def _lean(bias: float | None, error: float | None) -> float | None:
    if bias is None or not error:
        return None
    return bias if abs(bias) >= error * DIRECTIONAL_SHARE else None


def _actions(
    *,
    grade: Grade,
    horizon: Horizon,
    frequency: ForecastFrequency,
    confidence_level: float,
    downside_pct: float,
    concentration: Concentration | None,
    lean: float | None,
    realized_coverage: float | None,
    total: int,
) -> list[Action]:
    singular, plural = PERIOD_WORDS.get(frequency, ("period", "periods"))
    out: list[Action] = []

    if lean is not None:
        direction = "high" if lean > 0 else "low"
        out.append(
            Action(
                headline=f"Correct the plan {abs(lean):.1f}% {'down' if lean > 0 else 'up'}",
                detail=(
                    f"The last scored run came in {abs(lean):.1f}% {direction} and the miss "
                    "pointed one way rather than scattering, so the same lean is the "
                    "likeliest thing to repeat."
                ),
                urgency=0,
            )
        )

    if grade is Grade.INDICATIVE:
        out.append(
            Action(
                headline="Do not set targets from this run",
                detail=(
                    "Accuracy is too low for the period numbers to carry a commitment. "
                    "More history, or a target column with fewer gaps, moves this further "
                    "than any change of model."
                ),
                urgency=1,
            )
        )
    elif grade is Grade.DIRECTIONAL:
        out.append(
            Action(
                headline="Commit at the total, not period by period",
                detail=(
                    "The run is accurate enough to plan the horizon as a whole; single "
                    f"{plural} still move more than the forecast separates them by."
                ),
                urgency=2,
            )
        )

    if not horizon.covers_run:
        beyond = total - horizon.periods
        out.append(
            Action(
                headline=(
                    f"Re-forecast before {singular} {horizon.periods + 1}"
                    if horizon.periods
                    else "Re-forecast before committing"
                ),
                detail=(
                    f"The band stays narrow enough to plan against for "
                    f"{horizon.periods} {singular if horizon.periods == 1 else plural}. "
                    f"The remaining {beyond} carry a range wider than the forecast can "
                    "usefully split, so plan them at the total and refresh as actuals land."
                ),
                urgency=3,
            )
        )

    if downside_pct >= MATERIAL_DOWNSIDE_PCT:
        out.append(
            Action(
                headline=f"Hold cover for a {downside_pct:.0f}% shortfall",
                detail=(
                    "That is the gap between the base case and the worst case over the "
                    "horizon. Committing to the base case alone leaves it unfunded — stage "
                    "the commitment by period, or carry the difference as reserve."
                ),
                urgency=4,
            )
        )

    if concentration is not None and concentration.lopsided:
        leaders = ", ".join(concentration.leaders)
        out.append(
            Action(
                headline=(
                    f"Start with {concentration.count} of {concentration.total} series"
                    if concentration.count > 1
                    else f"Start with {leaders}"
                ),
                detail=(
                    f"{leaders} and the rest of that group carry {concentration.share:.0f}% "
                    "of the value at risk between them. Everything else can wait for the "
                    "next cycle."
                    if concentration.count > 1
                    else (
                        f"It carries {concentration.share:.0f}% of the value at risk on its "
                        "own. Everything else can wait for the next cycle."
                    )
                ),
                urgency=5,
            )
        )

    if intervals_held(realized_coverage, confidence_level) is False:
        out.append(
            Action(
                headline="Widen the range you plan against",
                detail=(
                    f"Actuals landed inside the {confidence_level * 100:.0f}% interval only "
                    f"{realized_coverage or 0.0:.0f}% of the time, so the band understates "
                    "what can happen. Treat the prepare-for number as a floor on capacity, "
                    "not a ceiling."
                ),
                urgency=6,
            )
        )

    if not out:
        out.append(
            Action(
                headline="Commit to the plan as it stands",
                detail=(
                    "Accuracy supports the period numbers, the band holds across the "
                    "horizon, and no single series carries the risk. Re-forecast when the "
                    "next actuals land."
                ),
                urgency=9,
            )
        )

    return sorted(out, key=lambda action: action.urgency)
