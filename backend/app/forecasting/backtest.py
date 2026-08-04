from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import numpy.typing as npt

from app.core.logging import get_logger
from app.forecasting.frequency import future_periods as make_future_periods
from app.forecasting.metrics import evaluate
from app.models.enums import ForecastFrequency, ModelKind

FloatArray = npt.NDArray[np.float64]

logger = get_logger(__name__)

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

    resolved_scheme = scheme or (
        "rolling" if n_observations >= ROLLING_WINDOW_SEASONS * period * 2 else "expanding"
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


ModelFactory = Callable[[FloatArray, list[date]], object]

DIVERGENCE_FACTOR = 1_000.0


def _diverged(predictions: FloatArray, y_train: FloatArray) -> str | None:
    if not np.all(np.isfinite(predictions)):
        return "The model produced non-finite forecasts."

    scale = float(np.max(np.abs(y_train[np.isfinite(y_train)]), initial=0.0))
    ceiling = DIVERGENCE_FACTOR * max(scale, 1.0)
    peak = float(np.max(np.abs(predictions)))
    if peak > ceiling:
        return (
            f"The model diverged: forecasts reached {peak:.3g} against a history "
            f"peaking at {scale:.3g}."
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
    return result
