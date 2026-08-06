from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from app.forecasting.backtest import BacktestResult
from app.models.enums import ModelKind

SCORING_RULE = (
    "score = 0.50*norm(wMAPE) + 0.30*norm(sMAPE) + 0.20*norm(RMSE) + complexity_penalty; "
    "metrics min-max normalised across candidates, lower is better"
)

METRIC_WEIGHTS: dict[str, float] = {
    "wmape": 0.50,
    "smape": 0.30,
    "rmse": 0.20,
}

INTERMITTENT_METRIC_WEIGHTS: dict[str, float] = {
    "mae": 0.50,
    "rmse": 0.50,
}


def metric_weights_for(intermittent: bool) -> dict[str, float]:
    return dict(INTERMITTENT_METRIC_WEIGHTS if intermittent else METRIC_WEIGHTS)


COMPLEXITY_PENALTY: dict[ModelKind, float] = {
    ModelKind.NAIVE: 0.00,
    ModelKind.SEASONAL_NAIVE: 0.01,
    ModelKind.THETA: 0.015,
    ModelKind.CROSTON: 0.015,
    ModelKind.HOLT_WINTERS: 0.02,
    ModelKind.ETS: 0.02,
    ModelKind.ENSEMBLE: 0.025,
    ModelKind.SARIMAX: 0.03,
    ModelKind.PROPHET: 0.035,
    ModelKind.GRADIENT_BOOSTING: 0.04,
}

PARAMETER_BUDGET: dict[ModelKind, int] = {
    ModelKind.NAIVE: 1,
    ModelKind.SEASONAL_NAIVE: 2,
    ModelKind.THETA: 3,
    ModelKind.CROSTON: 2,
    ModelKind.HOLT_WINTERS: 6,
    ModelKind.ETS: 7,
    ModelKind.ENSEMBLE: 10,
    ModelKind.SARIMAX: 8,
    ModelKind.PROPHET: 12,
    ModelKind.GRADIENT_BOOSTING: 24,
}

MAX_PENALTY_SCALE = 3.0


def penalty_scale(n_observations: int | None, model: ModelKind) -> float:
    if not n_observations or n_observations <= 0:
        return 1.0

    budget = PARAMETER_BUDGET.get(model, 4)
    observations_per_parameter = n_observations / budget
    if observations_per_parameter >= 20:
        return 1.0
    return float(min(MAX_PENALTY_SCALE, 20.0 / max(observations_per_parameter, 1.0)))


@dataclass(slots=True)
class ScoredCandidate:
    result: BacktestResult
    score: float
    rank: int
    selected: bool = False


@dataclass(slots=True)
class Selection:
    candidates: list[ScoredCandidate]
    winner: ScoredCandidate | None
    rationale: str
    scoring_rule: str = SCORING_RULE


OUTLIER_MAD_MULTIPLIER = 6.0


def _robust_ceiling(finite: list[float]) -> float:
    if len(finite) < 3:
        return max(finite)

    centre = statistics.median(finite)
    deviation = statistics.median([abs(value - centre) for value in finite])
    if deviation <= 0:
        return max(finite)
    return centre + OUTLIER_MAD_MULTIPLIER * deviation


def _normalise(values: list[float]) -> list[float]:
    finite = [v for v in values if math.isfinite(v)]
    if not finite:
        return [0.0] * len(values)

    ceiling = _robust_ceiling(finite)
    usable = [v for v in finite if v <= ceiling] or finite

    low, high = min(usable), max(usable)
    if math.isclose(low, high):
        return [0.0 if math.isfinite(v) and v <= high else 1.0 for v in values]

    span = high - low
    return [min(max((v - low) / span, 0.0), 1.0) if math.isfinite(v) else 1.0 for v in values]


def select_model(
    results: list[BacktestResult],
    metric_weights: dict[str, float] | None = None,
    complexity_penalties: dict[ModelKind, float] | None = None,
    n_observations: int | None = None,
    complexity_penalty_scale: float | None = None,
) -> Selection:
    weights = metric_weights or METRIC_WEIGHTS
    penalties = complexity_penalties or COMPLEXITY_PENALTY
    penalty_multiplier = complexity_penalty_scale if complexity_penalty_scale is not None else 1.0

    rule_str = (
        " + ".join(f"{w:.2f}*norm({m.upper()})" for m, w in weights.items())
        + " + complexity_penalty; metrics min-max normalised across candidates, lower is better"
    )

    usable = [r for r in results if not r.failed and math.isfinite(r.wmape)]

    if not usable:
        ran = [r for r in results if not r.failed]
        fallback = ran[0] if ran else (results[0] if results else None)
        unscored: list[ScoredCandidate] = [
            ScoredCandidate(result=r, score=float("inf"), rank=i + 1, selected=r is fallback)
            for i, r in enumerate(results)
        ]
        winner = next((c for c in unscored if c.selected), None)
        return Selection(
            candidates=unscored,
            winner=winner,
            rationale=(
                "No candidate produced a scoreable backtest; fell back to "
                f"{fallback.model.value if fallback else 'none'}."
            ),
            scoring_rule=rule_str,
        )

    normalised = {metric: _normalise([getattr(r, metric) for r in usable]) for metric in weights}

    scored: list[ScoredCandidate] = []
    for index, result in enumerate(usable):
        composite = sum(weight * normalised[metric][index] for metric, weight in weights.items())
        composite += (
            penalties.get(result.model, 0.0)
            * penalty_scale(n_observations, result.model)
            * penalty_multiplier
        )
        scored.append(ScoredCandidate(result=result, score=composite, rank=0))

    scored.sort(key=lambda c: c.score)
    for position, candidate in enumerate(scored, start=1):
        candidate.rank = position
    scored[0].selected = True
    winner = scored[0]

    scored_ids = {id(c.result) for c in scored}
    failed = [r for r in results if id(r) not in scored_ids]
    for offset, result in enumerate(failed, start=len(scored) + 1):
        scored.append(ScoredCandidate(result=result, score=float("inf"), rank=offset))

    return Selection(
        candidates=scored,
        winner=winner,
        rationale=_rationale(winner, scored),
        scoring_rule=rule_str,
    )


def _rationale(winner: ScoredCandidate, scored: list[ScoredCandidate]) -> str:
    """
    Why this method won, for the person who has to trust the number.

    This sentence sits on the dashboard and at the top of the report, so it
    says what the figures mean rather than naming them. wMAPE, sMAPE and RMSE
    are all still on the model screen for anyone who wants them; three
    acronyms and a composite score are not what the first screen is for.
    """
    name = winner.result.model.value.replace("_", " ").capitalize()
    folds = winner.result.n_folds
    parts = [
        f"{name} was off by {winner.result.wmape:.1f}% on average when tested against "
        f"{folds} stretch{'' if folds == 1 else 'es'} of history it had not seen."
    ]

    runner_up = next((c for c in scored[1:] if math.isfinite(c.score)), None)
    if runner_up is not None:
        runner_name = runner_up.result.model.value.replace("_", " ")
        if runner_up.score - winner.score < 0.05:
            parts.append(
                f"{runner_name.capitalize()} was so close behind that the simpler of "
                "the two was preferred."
            )
        else:
            parts.append(f"Next best was {runner_name}, off by {runner_up.result.wmape:.1f}%.")

    skipped = [c for c in scored if c.result.failed]
    if skipped:
        names = ", ".join(c.result.model.value.replace("_", " ") for c in skipped)
        parts.append(
            f"There was not enough history to test {names}, so {'it was' if len(skipped) == 1 else 'they were'} "
            "left out."
        )

    return " ".join(parts)
