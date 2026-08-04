
from __future__ import annotations

import time
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


def plan_backtest(
    n_observations: int,
    horizon: int,
    frequency: ForecastFrequency,
    *,
    max_folds: int | None = None,
    scheme: str = "expanding",
) -> BacktestPlan:
    from app.core.config import settings

    folds_limit = max_folds if max_folds is not None else settings.forecast_max_folds
    test_horizon = max(1, min(horizon, max(1, n_observations // 4)))

                                                                              
    initial_train = max(
                                                                                
        min(2 * _season(frequency), n_observations - test_horizon),
        max(3, n_observations // 2),
    )
    initial_train = min(initial_train, n_observations - test_horizon)

                                                                              
    if initial_train < 3:
        return BacktestPlan(scheme=scheme, horizon=test_horizon, cut_points=[], initial_train=0)

                                                                           
    cut_points: list[int] = []
    cut = n_observations - test_horizon
    while cut >= initial_train and len(cut_points) < folds_limit:
        cut_points.append(cut)
        cut -= test_horizon

    cut_points.reverse()

    return BacktestPlan(
        scheme=scheme,
        horizon=test_horizon,
        cut_points=cut_points,
        initial_train=initial_train,
        window=initial_train if scheme == "rolling" else None,
    )


def _season(frequency: ForecastFrequency) -> int:
    from app.forecasting.frequency import seasonal_period

    return seasonal_period(frequency)


def run_backtest(
    factory,                                                                    
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
            model = factory()
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
        except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
            result.failed = True
            result.failure_reason = f"{type(exc).__name__}: {exc}"
            logger.debug("Backtest fold failed for %s: %s", model_kind, exc)
            return result

        predictions = np.asarray(predictions, dtype=float).ravel()[: y_test.size]
        if predictions.size < y_test.size:
                                                                               
                                                                          
            pad = predictions[-1] if predictions.size else float("nan")
            predictions = np.concatenate([predictions, np.full(y_test.size - predictions.size, pad)])

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
