from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import numpy.typing as npt

from app.core.logging import get_logger
from app.forecasting.frequency import future_periods as make_future_periods
from app.forecasting.frequency import seasonal_period
from app.forecasting.metrics import evaluate, mase, winkler
from app.forecasting.models import Forecaster
from app.models.enums import ForecastFrequency, ModelKind

FloatArray = npt.NDArray[np.float64]

logger = get_logger(__name__)

#: z for a two-sided interval, for the levels a run can be started at. Kept
#: here rather than reaching for scipy, which this module otherwise does not
#: need for one lookup.
NORMAL_QUANTILE = {0.5: 0.6745, 0.8: 1.2816, 0.9: 1.6449, 0.95: 1.9600, 0.99: 2.5758}

MIN_FOLDS = 1
MAX_FOLDS_CEILING = 12
ROLLING_WINDOW_SEASONS = 4


@dataclass(slots=True)
class FoldResult:
    fold: int
    train_size: int
    test_size: int
    y_true: list[float]
    y_pred: list[float]


@dataclass(slots=True)
class BacktestResult:
    model: ModelKind
    folds: list[FoldResult] = field(default_factory=list)
    mae: float = float("nan")
    rmse: float = float("nan")
    smape: float = float("nan")
    wmape: float = float("nan")
    #: Error against the naive forecast a person would have made for free.
    #: The one that still reports a number where wMAPE has to give up.
    mase: float = float("nan")
    #: What this model's intervals would cost, in the units of the series.
    #: Point error cannot tell an honest band from a confident one.
    winkler: float = float("nan")
    fit_seconds: float = 0.0
    params: dict[str, object] = field(default_factory=dict)
    failed: bool = False
    failure_reason: str | None = None

    @property
    def n_folds(self) -> int:
        return len(self.folds)


@dataclass(slots=True)
class BacktestPlan:
    scheme: str
    horizon: int
    cut_points: list[int]
    initial_train: int
    window: int | None = None

    @property
    def n_folds(self) -> int:
        return len(self.cut_points)


def _affordable_folds(n_observations: int, test_horizon: int, initial_train: int) -> int:
    spare = n_observations - initial_train - test_horizon
    if spare < 0:
        return 0
    return 1 + spare // max(test_horizon, 1)


def plan_backtest(
    n_observations: int,
    horizon: int,
    frequency: ForecastFrequency,
    *,
    max_folds: int | None = None,
    scheme: str | None = None,
    seasonal_period: int | None = None,
) -> BacktestPlan:
    period = seasonal_period if seasonal_period and seasonal_period > 1 else _season(frequency)
    test_horizon = max(1, min(horizon, max(1, n_observations // 4)))

    initial_train = max(
        min(2 * period, n_observations - test_horizon),
        max(3, n_observations // 2),
    )
    initial_train = min(initial_train, n_observations - test_horizon)

    if initial_train < 3:
        return BacktestPlan(
            scheme=scheme or "expanding", horizon=test_horizon, cut_points=[], initial_train=0
        )

    affordable = _affordable_folds(n_observations, test_horizon, initial_train)
    folds_limit = max_folds if max_folds is not None else _adaptive_fold_limit(affordable)
    folds_limit = int(np.clip(folds_limit, MIN_FOLDS, MAX_FOLDS_CEILING))

    seasons_held = n_observations / period if period > 1 else n_observations / 12
    resolved_scheme = scheme or (
        "rolling" if seasons_held >= ROLLING_WINDOW_SEASONS * 2 else "expanding"
    )

    cut_points: list[int] = []
    cut = n_observations - test_horizon
    while cut >= initial_train and len(cut_points) < folds_limit:
        cut_points.append(cut)
        cut -= test_horizon

    cut_points.reverse()

    return BacktestPlan(
        scheme=resolved_scheme,
        horizon=test_horizon,
        cut_points=cut_points,
        initial_train=initial_train,
        window=initial_train if resolved_scheme == "rolling" else None,
    )


def _adaptive_fold_limit(affordable: int) -> int:
    from app.core.config import settings

    if affordable <= 0:
        return MIN_FOLDS
    return int(np.clip(affordable, MIN_FOLDS, max(settings.forecast_max_folds, MIN_FOLDS)))


def _season(frequency: ForecastFrequency) -> int:
    from app.forecasting.frequency import seasonal_period

    return seasonal_period(frequency)


ModelFactory = Callable[[FloatArray, list[date]], Forecaster]

DIVERGENCE_SIGMAS = 12.0


def _divergence_ceiling(y_train: FloatArray) -> float:
    finite = y_train[np.isfinite(y_train)]
    if finite.size == 0:
        return float("inf")

    level = float(np.max(np.abs(finite)))
    if finite.size < 3:
        return max(level * 4.0, 1.0)

    steps = np.abs(np.diff(finite))
    typical = float(np.median(steps)) if steps.size else 0.0
    spread = float(np.median(np.abs(steps - typical))) * 1.4826 if steps.size else 0.0
    volatility = max(typical + DIVERGENCE_SIGMAS * spread, float(np.std(finite, ddof=1)))

    return max(level + DIVERGENCE_SIGMAS * volatility, level * 2.0, 1.0)


def _diverged(predictions: FloatArray, y_train: FloatArray) -> str | None:
    if not np.all(np.isfinite(predictions)):
        return "The model produced non-finite forecasts."

    ceiling = _divergence_ceiling(y_train)
    peak = float(np.max(np.abs(predictions)))
    if peak > ceiling:
        level = float(np.max(np.abs(y_train[np.isfinite(y_train)]), initial=0.0))
        return (
            f"The model diverged: forecasts reached {peak:.3g} against a history "
            f"peaking at {level:.3g} (ceiling {ceiling:.3g})."
        )
    return None


def run_backtest(
    factory: ModelFactory,
    model_kind: ModelKind,
    y: FloatArray,
    periods: list[date],
    plan: BacktestPlan,
    frequency: ForecastFrequency,
    weights: FloatArray | None = None,
    confidence_level: float = 0.8,
) -> BacktestResult:
    result = BacktestResult(model=model_kind)

    if plan.n_folds == 0:
        result.failed = True
        result.failure_reason = "Not enough history to construct a single validation fold."
        return result

    all_true: list[float] = []
    all_pred: list[float] = []
    all_weights: list[float] = []
    started = time.perf_counter()
    last_params: dict[str, object] = {}

    for fold_index, cut in enumerate(plan.cut_points):
        train_start = 0 if plan.scheme == "expanding" else max(0, cut - (plan.window or cut))
        y_train = y[train_start:cut]
        periods_train = periods[train_start:cut]

        test_end = min(cut + plan.horizon, len(y))
        y_test = y[cut:test_end]
        test_periods = periods[cut:test_end]

        if y_test.size == 0 or y_train.size == 0:
            continue

        try:
            model = factory(y_train, periods_train)
            if y_train.size < model.min_observations:
                raise ValueError(
                    f"Fold {fold_index}: {y_train.size} training points, "
                    f"{model.min_observations} required."
                )
            model.fit(y_train, periods_train)
            forecast_periods = test_periods or make_future_periods(
                periods_train[-1], y_test.size, frequency
            )
            predictions = model.predict(y_test.size, forecast_periods)
            last_params = dict(model.params)
        except Exception as exc:
            result.failed = True
            result.failure_reason = f"{type(exc).__name__}: {exc}"
            logger.debug("Backtest fold failed for %s: %s", model_kind, exc)
            return result

        predictions = np.asarray(predictions, dtype=float).ravel()[: y_test.size]
        if predictions.size < y_test.size:
            pad = predictions[-1] if predictions.size else float("nan")
            predictions = np.concatenate(
                [predictions, np.full(y_test.size - predictions.size, pad)]
            )

        diverged = _diverged(predictions, y_train)
        if diverged is not None:
            result.failed = True
            result.failure_reason = diverged
            logger.debug("Backtest fold diverged for %s: %s", model_kind, diverged)
            return result

        result.folds.append(
            FoldResult(
                fold=fold_index,
                train_size=int(y_train.size),
                test_size=int(y_test.size),
                y_true=[float(v) for v in y_test],
                y_pred=[float(v) for v in predictions],
            )
        )
        all_true.extend(float(v) for v in y_test)
        all_pred.extend(float(v) for v in predictions)
        if weights is not None:
            all_weights.extend(float(v) for v in weights[cut:test_end])

    result.fit_seconds = time.perf_counter() - started
    result.params = last_params

    if not result.folds:
        result.failed = True
        result.failure_reason = "No fold produced a usable forecast."
        return result

    scores = evaluate(
        np.array(all_true),
        np.array(all_pred),
        np.array(all_weights) if all_weights else None,
    )
    result.mae = scores["mae"]
    result.rmse = scores["rmse"]
    result.smape = scores["smape"]
    result.wmape = scores["wmape"]
    result.mase = mase(
        np.array(all_true),
        np.array(all_pred),
        y[: plan.cut_points[0]] if plan.cut_points else y,
        seasonal_period(frequency),
    )
    result.winkler = interval_cost(result, confidence_level)
    return result


def interval_cost(result: BacktestResult, confidence_level: float) -> float:
    """
    What this model's intervals would have cost over the folds it was tested on.

    Each fold is scored against a band built from the *other* folds' residuals,
    so no fold helps size the interval it is then judged by. That leave-one-out
    step is the whole point: sizing a band from the errors it is about to be
    scored on always looks well calibrated.

    Needs two folds to say anything, and reports nothing rather than a
    flattering number when there is only one.
    """
    if len(result.folds) < 2:
        return float("nan")

    z = float(NORMAL_QUANTILE.get(round(confidence_level, 2), 1.2816))
    costs: list[float] = []

    for held_out in result.folds:
        residuals = [
            true - pred
            for fold in result.folds
            if fold is not held_out
            for true, pred in zip(fold.y_true, fold.y_pred, strict=True)
        ]
        if len(residuals) < 2:
            continue

        sigma = float(np.std(np.asarray(residuals, dtype=float)))
        if not np.isfinite(sigma) or sigma <= 0.0:
            continue

        predicted = np.asarray(held_out.y_pred, dtype=float)
        costs.append(
            winkler(
                np.asarray(held_out.y_true, dtype=float),
                predicted - z * sigma,
                predicted + z * sigma,
                confidence_level,
            )
        )

    finite = [cost for cost in costs if np.isfinite(cost)]
    return float(np.mean(finite)) if finite else float("nan")
