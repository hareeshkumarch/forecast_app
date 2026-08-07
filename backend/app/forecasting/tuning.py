from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

SEARCH_SEED = 20260804
MIN_VALIDATION_ROWS = 6
MAX_EVALUATIONS = 24
MIN_EVALUATIONS = 4
ROWS_PER_EVALUATION = 12
CACHE_LIMIT = 64


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
    from app.core.config import settings

    affordable = max(MIN_EVALUATIONS, n_rows // ROWS_PER_EVALUATION)
    return int(min(space_size, settings.tuning_max_evaluations, affordable))


def validation_splits(n_rows: int, horizon: int) -> list[tuple[int, int]]:
    from app.core.config import settings

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


def cache_key(name: str, matrix: FloatArray, target: FloatArray, space: SearchSpace) -> str:
    digest = hashlib.blake2s(digest_size=12)
    digest.update(name.encode())
    digest.update(str(sorted(space.choices)).encode())
    digest.update(np.asarray(matrix.shape, dtype=np.int64).tobytes())
    digest.update(np.ascontiguousarray(target, dtype=np.float64).tobytes())
    return digest.hexdigest()


def tuning_error(actual: FloatArray, predicted: FloatArray) -> float:
    denominator = float(np.sum(np.abs(actual)))
    if denominator <= 0.0:
        return float(np.mean(np.abs(actual - predicted)))
    return float(np.sum(np.abs(actual - predicted)) / denominator * 100.0)


def tune(
    name: str,
    matrix: FloatArray,
    target: FloatArray,
    space: SearchSpace,
    fit_predict: Callable[[dict[str, object], FloatArray, FloatArray, FloatArray], FloatArray],
    horizon: int,
) -> TuningResult:
    n_rows = int(matrix.shape[0])
    splits = validation_splits(n_rows, horizon)
    defaults = {key: values[len(values) // 2] for key, values in space.choices.items()}

    if not splits:
        return TuningResult(defaults, float("nan"), 0, "defaults_short_history", 0)

    key = cache_key(name, matrix, target, space)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    budget = evaluation_budget(n_rows, space.size())
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

    best_params, best_score = defaults, float("inf")

    for params in candidates:
        errors: list[float] = []
        for start, end in splits:
            try:
                predictions = fit_predict(params, matrix[:start], target[:start], matrix[start:end])
            except Exception:
                errors = []
                break

            actual = target[start:end]
            predictions = np.asarray(predictions, dtype=float).ravel()
            if predictions.size != actual.size or not np.all(np.isfinite(predictions)):
                errors = []
                break
            errors.append(tuning_error(actual, predictions))

        if not errors:
            continue

        score = float(np.mean(errors))
        if score < best_score:
            best_params, best_score = params, score

    result = TuningResult(best_params, best_score, len(candidates), method, len(splits))
    _CACHE.put(key, result)
    return result
