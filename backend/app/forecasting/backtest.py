from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from statistics import NormalDist

import numpy as np
import numpy.typing as npt

from app.core.config import settings
from app.core.logging import get_logger
from app.forecasting.frequency import future_periods as make_future_periods
from app.forecasting.frequency import seasonal_period
from app.forecasting.metrics import evaluate, mase, winkler
from app.forecasting.models import Forecaster
from app.forecasting.preparation import Preparation
from app.models.enums import ForecastFrequency, ModelKind

FloatArray = npt.NDArray[np.float64]

logger = get_logger(__name__)


def normal_quantile(confidence_level: float) -> float:
    """The two-sided z for this confidence level, computed rather than looked up.

    A five-entry table answered anything not in it with the 80% z. Ask for a
    92% interval and the cost of the bands was scored as though they were 80%
    ones — quietly, and only for the levels nobody had thought to tabulate.
    """
    level = min(max(float(confidence_level), 0.0), 1.0)
    if level <= 0.0:
        return 0.0
    if level >= 1.0:
        return float("inf")
    return float(NormalDist().inv_cdf(0.5 + level / 2.0))


MIN_FOLDS = 1
MAX_FOLDS_CEILING = 12
ROLLING_WINDOW_SEASONS = 4

#: How much of the plan a candidate has to survive to be scored at all. Below
#: it there is too little left to compare fairly against a model that fitted
#: everywhere — a model that only works on the two easiest folds should not be
#: ranked on those two alone.
MIN_FOLD_SHARE = 0.5


@dataclass(slots=True)
class FoldResult:
    fold: int
    train_size: int
    test_size: int
    y_true: list[float]
    y_pred: list[float]
    #: The run's observation weights over this fold's test window, when it has
    #: any. Kept per fold so anything rebuilding a score out of these folds —
    #: the ensemble does — can weigh it the way the members were weighed.
    y_weight: list[float] | None = None
    #: How many steps ahead each scored point actually was, counting from the
    #: cut. Only observed periods are kept, so a hole in the window makes
    #: position-in-list stop meaning horizon: drop one period and every error
    #: after it is attributed a step early. Anything that buckets residuals by
    #: horizon reads this rather than enumerating.
    y_step: list[int] = field(default_factory=list)

    def steps(self) -> list[int]:
        return self.y_step or list(range(1, len(self.y_true) + 1))


@dataclass(slots=True)
class BacktestResult:
    model: ModelKind
    folds: list[FoldResult] = field(default_factory=list)
    mae: float = float("nan")
    rmse: float = float("nan")
    smape: float = float("nan")
    wmape: float = float("nan")
    mase: float = float("nan")
    winkler: float = float("nan")
    fit_seconds: float = 0.0
    params: dict[str, object] = field(default_factory=dict)
    failed: bool = False
    failure_reason: str | None = None
    #: Folds the model could not produce a forecast for. A candidate scored on
    #: fewer folds than it was offered has been measured over less evidence,
    #: and the count is carried so that is visible rather than implied.
    folds_failed: int = 0

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
    if affordable <= 0:
        return MIN_FOLDS
    return int(np.clip(affordable, MIN_FOLDS, max(settings.forecast_max_folds, MIN_FOLDS)))


def _season(frequency: ForecastFrequency) -> int:
    from app.forecasting.frequency import seasonal_period

    return seasonal_period(frequency)


ModelFactory = Callable[[FloatArray, list[date]], Forecaster]


def _divergence_ceiling(y_train: FloatArray) -> float:
    finite = y_train[np.isfinite(y_train)]
    if finite.size == 0:
        return float("inf")

    level = float(np.max(np.abs(finite)))
    if finite.size < 3:
        return max(level * 4.0, 1.0)

    sigmas = settings.divergence_sigmas
    steps = np.abs(np.diff(finite))
    typical = float(np.median(steps)) if steps.size else 0.0
    spread = float(np.median(np.abs(steps - typical))) * 1.4826 if steps.size else 0.0
    volatility = max(typical + sigmas * spread, float(np.std(finite, ddof=1)))

    return max(level + sigmas * volatility, level * 2.0, 1.0)


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
    prepare: Preparation | None = None,
) -> BacktestResult:
    """Score a model over the plan's folds.

    `y` is the series as observed, with NaN in any period the data never had.
    `prepare` is applied to each fold's training slice — so a gap is
    interpolated from the training window alone, and outliers are clipped
    against its spread, rather than against a history that includes the very
    periods the fold is about to be scored on.

    A period that was never observed is not scored. Filling one and then
    counting the model's error against the number that filling invented
    reports an accuracy nobody measured.
    """
    result = BacktestResult(model=model_kind)

    if plan.n_folds == 0:
        result.failed = True
        result.failure_reason = "Not enough history to construct a single validation fold."
        return result

    preparation = prepare or Preparation()
    all_true: list[float] = []
    all_pred: list[float] = []
    all_weights: list[float] = []
    started = time.perf_counter()
    last_params: dict[str, object] = {}

    for fold_index, cut in enumerate(plan.cut_points):
        train_start = 0 if plan.scheme == "expanding" else max(0, cut - (plan.window or cut))
        y_train = preparation.apply(y[train_start:cut])
        periods_train = periods[train_start:cut]

        test_end = min(cut + plan.horizon, len(y))
        y_test = y[cut:test_end]
        test_periods = periods[cut:test_end]

        if y_test.size == 0 or y_train.size == 0:
            continue

        if not np.all(np.isfinite(y_train)):
            result.folds_failed += 1
            if result.failure_reason is None:
                result.failure_reason = (
                    "The training window for this fold has periods the data never "
                    "recorded, and this run was asked not to fill them."
                )
            continue

        observed = np.isfinite(y_test)
        if not np.any(observed):
            result.folds_failed += 1
            if result.failure_reason is None:
                result.failure_reason = (
                    "No period in this fold's validation window was ever recorded."
                )
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
            # One fold is not the verdict. SARIMAX fails to converge on the
            # shortest early window and fits every later one; discarding the
            # candidate outright threw away the model that would have won, and
            # reported the reason as though it were the whole story.
            result.folds_failed += 1
            if result.failure_reason is None:
                result.failure_reason = f"{type(exc).__name__}: {exc}"
            logger.debug("Backtest fold %d failed for %s: %s", fold_index, model_kind, exc)
            continue

        predictions = np.asarray(predictions, dtype=float).ravel()[: y_test.size]
        if predictions.size < y_test.size:
            # Padding the tail with the last value scores a forecast the model
            # never made, and it lands on the longest horizons — the ones the
            # intervals most depend on getting right.
            result.folds_failed += 1
            if result.failure_reason is None:
                result.failure_reason = (
                    f"The model returned {predictions.size} of the {y_test.size} step(s) "
                    "this fold asked for."
                )
            logger.debug(
                "Backtest fold %d returned %d of %d steps for %s",
                fold_index,
                predictions.size,
                y_test.size,
                model_kind,
            )
            continue

        diverged = _diverged(predictions, y_train)
        if diverged is not None:
            result.folds_failed += 1
            if result.failure_reason is None:
                result.failure_reason = diverged
            logger.debug("Backtest fold %d diverged for %s: %s", fold_index, model_kind, diverged)
            continue

        scored_true = y_test[observed]
        scored_pred = predictions[observed]
        fold_weights = (
            [float(v) for v in weights[cut:test_end][observed]] if weights is not None else None
        )
        result.folds.append(
            FoldResult(
                fold=fold_index,
                train_size=int(y_train.size),
                test_size=int(scored_true.size),
                y_true=[float(v) for v in scored_true],
                y_pred=[float(v) for v in scored_pred],
                y_weight=fold_weights,
                y_step=[int(step) + 1 for step in np.flatnonzero(observed)],
            )
        )
        all_true.extend(float(v) for v in scored_true)
        all_pred.extend(float(v) for v in scored_pred)
        if fold_weights is not None:
            all_weights.extend(fold_weights)

    result.fit_seconds = time.perf_counter() - started
    result.params = last_params

    if not result.folds:
        result.failed = True
        result.failure_reason = result.failure_reason or "No fold produced a usable forecast."
        return result

    if len(result.folds) < MIN_FOLD_SHARE * plan.n_folds:
        result.failed = True
        result.failure_reason = (
            f"Only {len(result.folds)} of {plan.n_folds} validation folds could be fitted"
            + (f" ({result.failure_reason})" if result.failure_reason else "")
            + ", which is too little to compare against models that fitted throughout."
        )
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
        preparation.apply(y[: plan.cut_points[0]]) if plan.cut_points else preparation.apply(y),
        seasonal_period(frequency),
    )
    result.winkler = interval_cost(result, confidence_level)
    return result


def interval_cost(result: BacktestResult, confidence_level: float) -> float:
    if len(result.folds) < 2:
        return float("nan")

    z = normal_quantile(confidence_level)
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
