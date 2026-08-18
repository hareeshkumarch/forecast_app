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
        seen: set[tuple] = set()
        candidates = []
        for _ in range(budget * 4):
            if len(candidates) >= budget:
                break
            params = space.sample(rng)
            signature = tuple(sorted(params.items(), key=lambda item: item[0]))
            if signature in seen:
                continue
            seen.add(signature)
            candidates.append(params)
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

    # `evaluations` counts candidates that produced a score. Reporting the
    # number tried made a search where every fit raised look like a search
    # that ran, and the defaults it fell back to look like a winner.
    method = method if evaluated else "defaults_all_candidates_failed"
    result = TuningResult(best_params, best_score, evaluated, method, len(splits))
    _CACHE.put(key, result)
    return result
