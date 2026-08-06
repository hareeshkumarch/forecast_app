"""
A combination of the models that actually did well, weighted by how well.

The roster already carried an ensemble, but it was three fixed members —
Theta, ETS and SARIMAX — combined by an unweighted median, all decided before
a single fold had been run. So it could not contain whichever model turned out
to win, and it gave the same say to a member that was twice as wrong as the
rest. On a series where gradient boosting or Prophet is the right answer, the
ensemble was a committee of three models nobody had picked.

This builds the combination *after* the backtest instead, out of the fold
predictions every candidate has already produced. Nothing is refitted to score
it: each candidate was tested on the same cuts of the same history, so their
predictions line up period for period and the blend can be scored on exactly
the folds its members were. Only the winner is ever fitted again.

Weighting is inverse-error, which is the standard choice and the defensible
one: it needs no parameters, it degrades gracefully as members get closer
together, and it cannot be gamed by a member that happens to sort first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.forecasting.backtest import BacktestResult, FoldResult, interval_cost
from app.forecasting.frequency import seasonal_period
from app.forecasting.metrics import evaluate, mase
from app.models.enums import ForecastFrequency, ModelKind

#: How many of the ranked candidates get a seat. Past three or four the added
#: members are, by construction, the ones that did worst, and their weight is
#: small enough that they mostly cost fitting time at the final refit.
MAX_MEMBERS = 4
MIN_MEMBERS = 2

#: A blend has to be enough better than its best member to be worth carrying
#: two extra model fits and a harder explanation. Expressed as a share of that
#: member's error, so it scales with the series rather than assuming units.
WORTH_THE_COMPLICATION = 0.02


@dataclass(slots=True)
class Blend:
    """The combination, its members, and how it did on the folds they shared."""

    members: tuple[ModelKind, ...]
    weights: dict[ModelKind, float]
    result: BacktestResult
    #: The error of the best single member, so the caller can say what the
    #: combination bought.
    best_member_error: float = float("nan")

    def describe(self) -> dict[str, object]:
        return {
            "members": [member.value for member in self.members],
            "combiner": "inverse_error_weighted_mean",
            "weights": {member.value: round(weight, 4) for member, weight in self.weights.items()},
        }


@dataclass(slots=True)
class _Aligned:
    """Candidates reduced to the folds they all share, in the same order."""

    models: list[ModelKind] = field(default_factory=list)
    predictions: list[list[list[float]]] = field(default_factory=list)
    truth: list[list[float]] = field(default_factory=list)
    fold_ids: list[int] = field(default_factory=list)


def _usable(results: list[BacktestResult]) -> list[BacktestResult]:
    return [
        result
        for result in results
        if not result.failed and result.folds and np.isfinite(result.wmape)
    ]


def _align(results: list[BacktestResult]) -> _Aligned | None:
    """
    Line the candidates up fold by fold.

    A candidate that skipped a fold — too little history for its own minimum —
    cannot contribute to that fold's blend, so the shared folds are the
    intersection. Anything that shares nothing with the others is left out
    rather than having its gaps filled in with someone else's numbers.
    """
    shared: set[int] | None = None
    for result in results:
        ids = {fold.fold for fold in result.folds}
        shared = ids if shared is None else shared & ids
    if not shared:
        return None

    order = sorted(shared)
    aligned = _Aligned(fold_ids=order)

    sizes = {
        fold_id: {
            len(fold.y_true) for result in results for fold in result.folds if fold.fold == fold_id
        }
        for fold_id in order
    }
    # A fold every candidate ran but disagreed about the length of cannot be
    # blended period by period, so it is dropped rather than truncated.
    order = [fold_id for fold_id in order if len(sizes[fold_id]) == 1]
    if not order:
        return None
    aligned.fold_ids = order

    reference = results[0]
    for fold_id in order:
        fold = next(f for f in reference.folds if f.fold == fold_id)
        aligned.truth.append(list(fold.y_true))

    for result in results:
        by_id = {fold.fold: fold for fold in result.folds}
        aligned.models.append(result.model)
        aligned.predictions.append([list(by_id[fold_id].y_pred) for fold_id in order])

    return aligned


def inverse_error_weights(errors: list[float]) -> list[float]:
    """
    Weight ∝ 1/error, normalised.

    A member that was perfect over the folds would divide by zero, so the
    smallest non-zero error in the set sets the floor — that keeps a lucky
    member dominant without letting it take the entire weight and turn the
    combination back into a single model.
    """
    finite = [error for error in errors if np.isfinite(error) and error > 0.0]
    floor = min(finite) if finite else 1.0

    raw = [1.0 / max(error, floor * 1e-3) if np.isfinite(error) else 0.0 for error in errors]
    total = sum(raw)
    if total <= 0.0:
        return [1.0 / len(errors)] * len(errors)
    return [value / total for value in raw]


def blend(
    results: list[BacktestResult],
    *,
    frequency: ForecastFrequency,
    confidence_level: float = 0.8,
    weights: np.ndarray | None = None,
    max_members: int = MAX_MEMBERS,
) -> Blend | None:
    """
    The best combination the backtest supports, or nothing if it supports none.

    Returns `None` rather than a token blend when there are too few usable
    candidates, when they share no fold, or when the combination is not
    meaningfully better than simply taking the best of them — a combination
    that ties with its best member is a harder thing to explain for no gain.
    """
    usable = sorted(_usable(results), key=lambda result: result.mae)
    if len(usable) < MIN_MEMBERS:
        return None

    chosen = usable[: max(MIN_MEMBERS, min(max_members, len(usable)))]
    aligned = _align(chosen)
    if aligned is None:
        return None

    share = inverse_error_weights([result.mae for result in chosen])

    folds: list[FoldResult] = []
    all_true: list[float] = []
    all_pred: list[float] = []

    for index, fold_id in enumerate(aligned.fold_ids):
        truth = aligned.truth[index]
        stacked = np.vstack(
            [np.asarray(member[index], dtype=float) for member in aligned.predictions]
        )
        combined = np.average(stacked, axis=0, weights=share)

        folds.append(
            FoldResult(
                fold=fold_id,
                train_size=0,
                test_size=len(truth),
                y_true=list(truth),
                y_pred=[float(value) for value in combined],
            )
        )
        all_true.extend(truth)
        all_pred.extend(float(value) for value in combined)

    if not all_true:
        return None

    result = BacktestResult(model=ModelKind.ENSEMBLE, folds=folds)
    scores = evaluate(np.array(all_true), np.array(all_pred), weights)
    result.mae = scores["mae"]
    result.rmse = scores["rmse"]
    result.smape = scores["smape"]
    result.wmape = scores["wmape"]
    result.mase = mase(
        np.array(all_true), np.array(all_pred), np.array(all_true), seasonal_period(frequency)
    )
    result.winkler = interval_cost(result, confidence_level)
    result.fit_seconds = sum(member.fit_seconds for member in chosen)

    best = min(member.mae for member in chosen)
    if not np.isfinite(result.mae) or result.mae > best * (1.0 - WORTH_THE_COMPLICATION):
        return None

    members = tuple(aligned.models)
    result.params = {
        "members": [member.value for member in members],
        "combiner": "inverse_error_weighted_mean",
        "weights": {
            member.value: round(weight, 4) for member, weight in zip(members, share, strict=True)
        },
        "chosen_from": len(usable),
    }

    return Blend(
        members=members,
        weights=dict(zip(members, share, strict=True)),
        result=result,
        best_member_error=best,
    )
