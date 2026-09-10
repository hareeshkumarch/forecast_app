from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from app.core.config import settings

FloatArray = npt.NDArray[np.float64]

SEARCH_SEED = 20260804
MIN_VALIDATION_ROWS = 6
MIN_EVALUATIONS = 4
ROWS_PER_EVALUATION = 12
CACHE_LIMIT = 64
SURVIVOR_SHARE = 1.0 / 3.0
MIN_SURVIVORS = 3
#: Coordinate-descent passes from the winner. Two is enough to leave a plateau
#: it landed beside; more is a series with a hundred rows being polished while
#: the run's minute goes somewhere else.
MAX_REFINEMENT_STEPS = 2
#: Fits the refinement may spend even when the sampling budget was tiny.
MIN_REFINEMENT = 4


def as_int(value: object, default: int = 0) -> int:
    return int(value) if isinstance(value, int | float | str) else default


def as_float(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float | str) else default


@dataclass(slots=True)
class SearchSpace:
    choices: dict[str, Sequence[object]]

    def size(self) -> int:
        total = 1
        for values in self.choices.values():
            total *= max(len(values), 1)
        return total

    def sample(self, rng: np.random.Generator) -> dict[str, object]:
        return {key: values[rng.integers(len(values))] for key, values in self.choices.items()}

    def grid(self) -> list[dict[str, object]]:
        combinations: list[dict[str, object]] = [{}]
        for key, values in self.choices.items():
            combinations = [{**partial, key: value} for partial in combinations for value in values]
        return combinations

    def stratified(self, rng: np.random.Generator, count: int) -> list[dict[str, object]]:
        """`count` distinct settings, covering every value of every parameter.

        Independent random draws leave holes: with eight candidates over a
        five-value parameter, the chance that some value is never tried at all
        is better than one in two, and a search that never tried a setting
        cannot report that it was worse. This deals each parameter's values out
        like a shuffled deck instead, so the levels are spread by construction
        and only which ones meet each other is left to chance.
        """
        columns: dict[str, list[object]] = {}
        for key, values in self.choices.items():
            dealt: list[object] = []
            while len(dealt) < count:
                order = list(values)
                rng.shuffle(order)  # type: ignore[arg-type]
                dealt.extend(order)
            columns[key] = dealt[:count]

        seen: set[tuple] = set()
        sampled: list[dict[str, object]] = []
        for index in range(count):
            params = {key: column[index] for key, column in columns.items()}
            signature = tuple(sorted(params.items(), key=lambda item: item[0]))
            if signature in seen:
                continue
            seen.add(signature)
            sampled.append(params)
        return sampled


@dataclass(slots=True)
class TuningResult:
    params: dict[str, object]
    score: float
    evaluations: int
    method: str
    folds: int

    def as_dict(self) -> dict[str, object]:
        return {
            "tuning_method": self.method,
            "tuning_evaluations": self.evaluations,
            "tuning_folds": self.folds,
            "tuning_score": None if not np.isfinite(self.score) else round(self.score, 6),
        }


@dataclass(slots=True)
class _Cache:
    entries: dict[str, TuningResult] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)

    def get(self, key: str) -> TuningResult | None:
        return self.entries.get(key)

    def put(self, key: str, value: TuningResult) -> None:
        if key not in self.entries and len(self.order) >= CACHE_LIMIT:
            oldest = self.order.pop(0)
            self.entries.pop(oldest, None)
        if key not in self.entries:
            self.order.append(key)
        self.entries[key] = value


_CACHE = _Cache()


def evaluation_budget(n_rows: int, space_size: int) -> int:
    affordable = max(MIN_EVALUATIONS, n_rows // ROWS_PER_EVALUATION)
    return int(min(space_size, settings.tuning_max_evaluations, affordable))


def search_width(n_rows: int, space_size: int, folds: int) -> int:
    """How many candidates the budget buys once cheap screening is priced in."""
    budget = evaluation_budget(n_rows, space_size)
    if folds < 2:
        return budget

    fits = budget * folds
    affordable = fits / (1.0 + folds * SURVIVOR_SHARE)
    return int(min(space_size, max(budget, round(affordable))))


def validation_splits(n_rows: int, horizon: int) -> list[tuple[int, int]]:
    min_rows = settings.tuning_min_validation_rows
    if n_rows < min_rows * 2:
        return []

    block = max(min_rows, min(horizon, n_rows // 5))
    folds = 1 if n_rows < 60 else 2 if n_rows < 200 else 3

    splits: list[tuple[int, int]] = []
    for index in range(folds):
        end = n_rows - index * block
        start = end - block
        if start < min_rows * 2:
            break
        splits.append((start, end))

    return list(reversed(splits))


def cache_key(
    name: str,
    matrix: FloatArray,
    target: FloatArray,
    space: SearchSpace,
    horizon: int,
) -> str:
    """Everything the answer depends on, and nothing it does not.

    The features have to be hashed by content. Hashing only their shape means
    two different feature sets over the same target — which is exactly what a
    driver column being added or dropped produces — collide, and the second
    one is answered with the first one's hyperparameters. So do the search
    space's *values*: a space with the same keys and different candidates is a
    different search.
    """
    digest = hashlib.blake2s(digest_size=16)
    digest.update(name.encode())
    digest.update(repr([(key, list(space.choices[key])) for key in sorted(space.choices)]).encode())
    digest.update(str(horizon).encode())
    digest.update(np.asarray(matrix.shape, dtype=np.int64).tobytes())
    digest.update(np.ascontiguousarray(matrix, dtype=np.float64).tobytes())
    digest.update(np.ascontiguousarray(target, dtype=np.float64).tobytes())
    return digest.hexdigest()


def tuning_error(actual: FloatArray, predicted: FloatArray) -> float:
    denominator = float(np.sum(np.abs(actual)))
    if denominator <= 0.0:
        return float(np.mean(np.abs(actual - predicted)))
    return float(np.sum(np.abs(actual - predicted)) / denominator * 100.0)


def blended_error(
    actual: FloatArray,
    predicted: FloatArray,
    weights: dict[str, float] | None,
    insample: FloatArray | None = None,
    season: int = 1,
) -> float:
    """Score a candidate the way the run will score the model it belongs to.

    Tuning that minimises one error and selection that minimises another will
    disagree, and the disagreement is silent: the search hands over the
    hyperparameters that were best at the wrong thing.
    """
    if not weights:
        return tuning_error(actual, predicted)

    from app.forecasting.metrics import evaluate, mase

    scores = evaluate(actual, predicted)
    scale = float(np.mean(np.abs(actual)))
    if not np.isfinite(scale) or scale <= 0.0:
        scale = 1.0

    # Real MASE where the training window is on hand. Scaling MAE by the level
    # of the series instead measures something else, and on a seasonal series
    # the two rank candidates differently — which is the disagreement with
    # selection this function exists to close.
    scaled_mae = scores["mae"] / scale * 100.0
    seasonal = (
        mase(actual, predicted, insample, max(1, season)) * 100.0
        if insample is not None and np.size(insample) > max(1, season)
        else float("nan")
    )

    comparable = {
        "wmape": scores["wmape"],
        "mase": seasonal if np.isfinite(seasonal) else scaled_mae,
        "rmse": scores["rmse"] / scale * 100.0,
        "mae": scaled_mae,
    }

    total = sum(weight for metric, weight in weights.items() if metric in comparable)
    if total <= 0.0:
        return tuning_error(actual, predicted)

    return (
        sum(
            weight * comparable[metric]
            for metric, weight in weights.items()
            if metric in comparable
        )
        / total
    )


#: Given the parameters and a half-open range of validation rows, train on
#: everything before `start` and predict rows `[start, end)`. The caller owns
#: the prediction because only the caller knows how the model will really be
#: asked for a forecast — reading the answers out of a design matrix built
#: from the actuals measures one-step-ahead accuracy with the truth in hand,
#: and a recursive model never has that.
FitPredict = Callable[[dict[str, object], int, int], FloatArray]


def tune(
    name: str,
    matrix: FloatArray,
    target: FloatArray,
    space: SearchSpace,
    fit_predict: FitPredict,
    horizon: int,
    metric_weights: dict[str, float] | None = None,
    season: int = 1,
) -> TuningResult:
    n_rows = int(matrix.shape[0])
    splits = validation_splits(n_rows, horizon)
    defaults = {key: values[len(values) // 2] for key, values in space.choices.items()}

    if not splits:
        return TuningResult(defaults, float("nan"), 0, "defaults_short_history", 0)

    key = cache_key(name, matrix, target, space, horizon)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    budget = search_width(n_rows, space.size(), len(splits))
    rng = np.random.default_rng(SEARCH_SEED)

    if space.size() <= budget:
        candidates = space.grid()
        method = "grid"
    else:
        candidates = space.stratified(rng, budget)
        method = "random"

    def score_over(params: dict[str, object], folds: list[tuple[int, int]]) -> float:
        errors: list[float] = []
        for start, end in folds:
            try:
                predictions = fit_predict(params, start, end)
            except Exception:
                return float("nan")

            actual = target[start:end]
            predictions = np.asarray(predictions, dtype=float).ravel()
            if predictions.size != actual.size or not np.all(np.isfinite(predictions)):
                return float("nan")
            errors.append(
                blended_error(actual, predictions, metric_weights, target[:start], season)
            )

        return float(np.mean(errors)) if errors else float("nan")

    contenders = candidates
    if len(splits) >= 2 and len(candidates) > MIN_SURVIVORS:
        # Successive halving: every candidate is screened on the earliest fold,
        # and only the survivors pay for the rest. A candidate that fails a fold
        # is dropped either way, so screening on one loses nothing.
        screened = [
            (score_over(params, splits[:1]), index) for index, params in enumerate(candidates)
        ]
        alive = sorted((score, index) for score, index in screened if np.isfinite(score))
        keep = max(MIN_SURVIVORS, int(len(candidates) * SURVIVOR_SHARE))
        contenders = [candidates[index] for _, index in alive[:keep]]
        method = f"{method}_halving"

    best_params, best_score = defaults, float("inf")
    evaluated = 0

    for params in contenders:
        score = score_over(params, splits)
        if not np.isfinite(score):
            continue

        evaluated += 1
        if score < best_score:
            best_params, best_score = params, score

    if evaluated:
        best_params, best_score, refined = _refine(
            best_params, best_score, space, score_over, splits, budget
        )
        evaluated += refined
        if refined:
            method = f"{method}_refined"

    # `evaluations` counts candidates that produced a score. Reporting the
    # number tried made a search where every fit raised look like a search
    # that ran, and the defaults it fell back to look like a winner.
    method = method if evaluated else "defaults_all_candidates_failed"
    result = TuningResult(best_params, best_score, evaluated, method, len(splits))
    _CACHE.put(key, result)
    return result


def _neighbours(space: SearchSpace, params: dict[str, object]) -> list[dict[str, object]]:
    """The settings one step from this one, along each parameter in turn.

    A step means the adjacent entry in that parameter's list, so the lists are
    read as ordered — which they are: every space in `app/forecasting/models.py`
    lists depths, rates and window lengths in order. For an unordered list this
    still works, it just explores in the order the values were written.
    """
    around: list[dict[str, object]] = []
    for key, values in space.choices.items():
        ordered = list(values)
        try:
            at = ordered.index(params[key])
        except (KeyError, ValueError):
            continue
        for step in (-1, 1):
            index = at + step
            if 0 <= index < len(ordered):
                around.append({**params, key: ordered[index]})
    return around


def _refine(
    params: dict[str, object],
    score: float,
    space: SearchSpace,
    score_over: Callable[[dict[str, object], list[tuple[int, int]]], float],
    splits: list[tuple[int, int]],
    budget: int,
) -> tuple[dict[str, object], float, int]:
    """Walk downhill from the winner, one parameter at a time.

    The search picked the best of a scattered sample and stopped, which leaves
    it at whichever sampled point happened to be lowest rather than at the
    bottom of the dip that point is in — and with a coarse sample the two are
    routinely a step or two apart. Coordinate descent from the winner is the
    cheapest way to close that: it costs a couple of fits per parameter and it
    only ever moves to something measurably better, so it cannot make the
    answer worse than the point it started from.

    Bounded twice over — by a step count, and by a share of the same budget the
    sampling was drawn against — because refining forever on a series that has
    a hundred rows is spending the run's minute in the wrong place.

    Returns the number of neighbours that produced a score, not the number
    tried: `evaluations` means the same thing everywhere it is reported, and a
    refinement whose every fit raised must not look like one that ran.
    """
    allowance = max(MIN_REFINEMENT, budget // 2)
    attempts = 0
    scored = 0
    visited = {_signature(params)}

    for _ in range(MAX_REFINEMENT_STEPS):
        improved = False
        for candidate in _neighbours(space, params):
            signature = _signature(candidate)
            if signature in visited:
                continue
            visited.add(signature)

            if attempts >= allowance:
                return params, score, scored
            attempts += 1

            trial = score_over(candidate, splits)
            if not np.isfinite(trial):
                # A setting the model could not fit. It cost a fit and it did
                # not produce a score, and `evaluations` counts scores — see
                # the note where it is reported.
                continue
            scored += 1
            if trial < score:
                params, score, improved = candidate, trial, True
                break

        if not improved:
            break

    return params, score, scored


def _signature(params: dict[str, object]) -> tuple:
    return tuple(sorted(params.items(), key=lambda item: item[0]))
