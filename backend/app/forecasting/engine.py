from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from threading import Lock
from typing import Any, TypedDict

import numpy as np
import numpy.typing as npt

from app.core.budget import RunTimings, Stage
from app.core.config import settings
from app.core.logging import get_logger
from app.forecasting import combination
from app.forecasting.backtest import (
    BacktestPlan,
    BacktestResult,
    ModelFactory,
    plan_backtest,
    run_backtest,
)
from app.forecasting.calibration import (
    HeldOutPoint,
    Interval,
    calibrate,
    conformal_halfwidths,
    measure_coverage,
    realised_coverage,
)
from app.forecasting.decomposition import Driver, decompose_drivers
from app.forecasting.diagnostics import (
    SeriesProfile,
    detect_changepoints,
    minimum_history,
    profile_series,
)
from app.forecasting.drivers import DriverLink, DriverPanel, DriverSource, describe
from app.forecasting.frequency import future_periods
from app.forecasting.hierarchy import (
    Node,
    all_non_negative,
    build_tree,
    coherence_gap,
    reconcile_to_total,
    reconcile_tree,
    walk,
)
from app.forecasting.metrics import accuracy_from_wmape, forecast_value_add
from app.forecasting.models import (
    EnsembleForecaster,
    Forecaster,
    build_candidate,
    build_candidates,
    unavailable_models,
)
from app.forecasting.preparation import Preparation
from app.forecasting.routing import BASELINE_MODELS, route
from app.forecasting.scenarios import IntervalBands, build_intervals
from app.forecasting.selection import ScoredCandidate, metric_weights_for, select_model
from app.forecasting.transforms import TransformedForecaster, build_transform
from app.models.enums import ForecastFrequency, ModelKind, SeriesStatus

FloatArray = npt.NDArray[np.float64]

logger = get_logger(__name__)

SCALABLE_FRACTION = 1e-6


@dataclass(slots=True)
class SeriesInput:
    periods: list[date]
    values: list[float]
    weights: list[float] | None = None


@dataclass(slots=True)
class SegmentInput:
    label: str
    current_total: float
    prior_total: float | None
    series: list[float] = field(default_factory=list)
    periods: list[date] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    key: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ForecastInput:
    series: SeriesInput
    frequency: ForecastFrequency
    horizon: int
    confidence_level: float = 0.8
    regions: list[SegmentInput] = field(default_factory=list)
    categories: list[SegmentInput] = field(default_factory=list)
    quantity: list[float] | None = None
    max_folds: int | None = None
    metric_weights: dict[str, float] | None = None
    model_options: dict[str, object] | None = None
    quality: dict[str, object] = field(default_factory=dict)
    drivers: dict[str, list[float]] = field(default_factory=dict)
    target_label: str = "the total"
    #: What to do to a window of history before fitting on it. Held as an
    #: instruction rather than applied to `series.values` up front, so each
    #: backtest fold can apply it to its own training slice.
    preparation: Preparation = field(default_factory=Preparation)


@dataclass(slots=True)
class SegmentOutput:
    label: str
    forecast_value: float
    prior_year_value: float | None
    change_vs_last_year: float | None
    accuracy: float | None
    share: float
    model: str | None = None
    accuracy_measured: bool = False


@dataclass(slots=True)
class ForecastOutput:
    selected_model: ModelKind
    selection_rationale: str
    scoring_rule: str
    used_fallback: bool
    fallback_reason: str | None

    history_periods: list[date]
    history_values: list[float]
    fitted_values: list[float | None]

    forecast_periods: list[date]
    point_forecast: list[float]
    lower_bound: list[float]
    upper_bound: list[float]
    best_case: list[float]
    base_case: list[float]
    worst_case: list[float]

    metrics: dict[str, float]
    candidates: list[CandidateRow]
    interval_method: str
    diagnostics: dict[str, object] = field(default_factory=dict)
    #: What each stage of this run cost, against what it was allowed to cost.
    timings: RunTimings = field(default_factory=RunTimings)

    regions: list[SegmentOutput] = field(default_factory=list)
    categories: list[SegmentOutput] = field(default_factory=list)
    drivers: list[Driver] = field(default_factory=list)
    leading_columns: list[DriverLink] = field(default_factory=list)


class CandidateRow(TypedDict):
    model: str
    rank: int
    selected: bool
    mae: float | None
    rmse: float | None
    smape: float | None
    wmape: float | None
    mase: float | None
    winkler: float | None
    score: float | None
    folds: int
    fit_seconds: float
    params: dict[str, object]
    failed: bool
    failure_reason: str | None


class InsufficientDataError(Exception):
    pass


TRANSFORMABLE = {
    ModelKind.HOLT_WINTERS,
    ModelKind.THETA,
    ModelKind.SARIMAX,
    ModelKind.GRADIENT_BOOSTING,
}

WindowKey = tuple[int, date, date]


@dataclass(slots=True)
class WindowFeatureCache:
    profiles: dict[WindowKey, SeriesProfile] = field(default_factory=dict)
    panels: dict[WindowKey, DriverPanel] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def profile_for(
        self,
        key: WindowKey,
        values: FloatArray,
        frequency: ForecastFrequency,
    ) -> SeriesProfile:
        with self.lock:
            cached = self.profiles.get(key)
            if cached is None:
                cached = profile_series(values, frequency)
                self.profiles[key] = cached
            return cached

    def panel_for(
        self,
        key: WindowKey,
        source: DriverSource,
        values: FloatArray,
        periods: list[date],
    ) -> DriverPanel:
        with self.lock:
            cached = self.panels.get(key)
            if cached is None:
                cached = source.panel_for(values, periods)
                self.panels[key] = cached
            return cached


def _make_factory(
    kind: ModelKind,
    frequency: ForecastFrequency,
    options: dict[str, object] | None,
    drivers: DriverSource | None = None,
    feature_cache: WindowFeatureCache | None = None,
) -> ModelFactory:
    """A model built from the window it is about to be fitted on.

    Everything the model configures itself from — the seasonal period, the
    variance transform, which columns lead the target — is measured inside
    the window. The factory is handed each fold's training slice, so none of
    those choices can be made with the fold's validation data in hand.
    """

    # Shared by every fold of one backtest: the shape of a series does not
    # change between folds, so ETS and Holt-Winters search for it once and
    # refit only its parameters afterwards. Chosen on the first fold's
    # training slice, so nothing sees a period it is about to be scored on.
    shape_cache: dict[str, object] = {}

    def factory(y_train: FloatArray, periods_train: list[date]) -> Forecaster:
        key = (len(periods_train), periods_train[0], periods_train[-1])
        window_profile = (
            feature_cache.profile_for(key, y_train, frequency)
            if feature_cache is not None
            else profile_series(y_train, frequency)
        )
        panel = (
            feature_cache.panel_for(key, drivers, y_train, periods_train)
            if feature_cache is not None and drivers is not None
            else drivers.panel_for(y_train, periods_train)
            if drivers is not None
            else None
        )
        model = build_candidate(kind, frequency, options, window_profile, panel, shape_cache)
        if kind in TRANSFORMABLE:
            return TransformedForecaster(model, build_transform(y_train, window_profile))
        return model

    return factory


def _backtest_candidate(
    args: tuple[
        ModelKind,
        ForecastFrequency,
        dict[str, object],
        DriverSource | None,
        FloatArray,
        list[date],
        BacktestPlan,
        FloatArray | None,
        float,
        Preparation | None,
    ],
) -> BacktestResult:
    """One candidate, scored. Module level so it can be sent to a subprocess."""
    kind, frequency, options, source, observed, periods, plan, weights, level, prepare = args
    return run_backtest(
        _make_factory(kind, frequency, options, source),
        kind,
        observed,
        periods,
        plan,
        frequency,
        weights,
        level,
        prepare=prepare,
    )


def _columns_used(model: Forecaster, panel: DriverPanel) -> list[DriverLink]:
    if not panel:
        return []

    params = model.params
    used = params.get("drivers_used")
    if not isinstance(used, list) or not used:
        return []

    return [link for link in panel.links if any(link.name in str(entry) for entry in used)]


ProgressCallback = Callable[[str, int, int, str], None]


def run_forecast(
    payload: ForecastInput, progress_callback: ProgressCallback | None = None
) -> ForecastOutput:
    #: As observed, NaN where the calendar expects a period the data never had.
    observed = np.asarray(payload.series.values, dtype=float)
    #: The same series with the run's gap fill and outlier treatment applied
    #: over its whole length. Correct for the final fit, where the whole
    #: history is the training data, and for everything the user is shown —
    #: but never handed to the backtest, which prepares each fold for itself.
    values = payload.preparation.apply(observed)
    periods = list(payload.series.periods)
    weights = (
        np.asarray(payload.series.weights, dtype=float)
        if payload.series.weights is not None
        else None
    )

    if values.size < 2:
        raise InsufficientDataError(
            f"Only {values.size} observation(s) after aggregation; at least 2 are required."
        )

    frequency = payload.frequency
    horizon = payload.horizon

    timings = RunTimings()
    with timings.measure(Stage.CLASSIFY):
        profile = profile_series(values, frequency)
    floor = minimum_history(profile)

    # Every model that tunes its own hyperparameters searches against the
    # metrics this run is scored by, so the search and the selection cannot
    # disagree about what a good forecast is.
    scoring_weights = payload.metric_weights or metric_weights_for(profile.intermittent)
    model_options = {**(payload.model_options or {}), "metric_weights": scoring_weights}

    source = DriverSource(
        periods=periods,
        columns={name: np.asarray(column, dtype=float) for name, column in payload.drivers.items()},
        horizon=horizon,
        frequency=frequency,
    )
    # The roster of candidate models is a structural choice — whether it is
    # worth offering a driver-using variant at all — so it is made from the
    # whole history, which is also what the final model is fitted on. What
    # each fold *fits* is discovered inside that fold.
    with timings.measure(Stage.FEATURES):
        panel = source.panel_for(values, periods)

    full_window = (len(periods), periods[0], periods[-1])
    feature_cache = WindowFeatureCache(
        profiles={full_window: profile},
        panels={full_window: panel},
    )

    used_fallback = False
    fallback_reason: str | None = None

    plan = plan_backtest(
        values.size,
        horizon,
        frequency,
        max_folds=payload.max_folds,
        seasonal_period=profile.seasonal_period,
    )

    if values.size < floor or plan.n_folds == 0:
        used_fallback = True
        fallback_reason = _fallback_reason(values.size, floor, frequency, plan.n_folds, profile)
        seasonal_ready = profile.seasonal_period > 1 and values.size >= profile.seasonal_period
        candidates = [
            build_candidate(
                ModelKind.SEASONAL_NAIVE if seasonal_ready else ModelKind.NAIVE,
                frequency,
                model_options,
                profile,
            )
        ]
    else:
        candidates = build_candidates(frequency, model_options, profile, panel)

    results: list[BacktestResult] = []
    candidate_total = len(candidates)
    fit_started = time.perf_counter()

    def evaluate_candidate(candidate: Forecaster) -> BacktestResult:
        kind = candidate.kind
        return run_backtest(
            _make_factory(kind, frequency, model_options, source, feature_cache),
            kind,
            observed,
            periods,
            plan,
            frequency,
            weights,
            payload.confidence_level,
            prepare=payload.preparation,
        )

    work = [
        (
            candidate.kind,
            frequency,
            model_options,
            source,
            observed,
            periods,
            plan,
            weights,
            payload.confidence_level,
            payload.preparation,
        )
        for candidate in candidates
    ]

    def announce(done: int, label: str) -> None:
        if progress_callback is not None:
            progress_callback("backtesting", done, candidate_total, label)

    model_workers = min(settings.forecast_model_concurrency, candidate_total)
    lanes = min(settings.forecast_candidate_workers, candidate_total)

    if model_workers > 1:
        # Thread-level parallelism with feature caching.
        indexed: dict[int, BacktestResult] = {}
        if progress_callback is not None:
            progress_callback(
                "backtesting",
                0,
                candidate_total,
                f"Backtesting {candidate_total} candidate models with {model_workers} workers...",
            )
        with ThreadPoolExecutor(
            max_workers=model_workers,
            thread_name_prefix="forecast-model",
        ) as pool:
            futures = {
                pool.submit(evaluate_candidate, candidate): (index, candidate.kind)
                for index, candidate in enumerate(candidates)
            }
            for completed, future in enumerate(as_completed(futures), start=1):
                index, kind = futures[future]
                indexed[index] = future.result()
                if progress_callback is not None:
                    progress_callback(
                        "backtesting",
                        completed,
                        candidate_total,
                        f"Backtested {kind.value.replace('_', ' ')} ({completed} of {candidate_total}).",
                    )
        results = [indexed[index] for index in range(candidate_total)]
    elif lanes > 1:
        # Process-level parallelism without feature caching.
        results = [None] * candidate_total  # type: ignore[list-item]
        announce(0, f"Backtesting {candidate_total} candidate models...")
        with ProcessPoolExecutor(max_workers=lanes) as pool:
            futures = {pool.submit(_backtest_candidate, item): i for i, item in enumerate(work)}
            for done, future in enumerate(as_completed(futures), start=1):
                index = futures[future]
                results[index] = future.result()
                announce(done, f"Backtested {done} of {candidate_total} candidate models.")
    else:
        for candidate_index, candidate in enumerate(candidates, start=1):
            if progress_callback is not None:
                progress_callback(
                    "backtesting",
                    candidate_index - 1,
                    candidate_total,
                    f"Backtesting {candidate.kind.value.replace('_', ' ')} ({candidate_index} of {candidate_total})...",
                )
            results.append(evaluate_candidate(candidate))
            if progress_callback is not None:
                progress_callback(
                    "backtesting",
                    candidate_index,
                    candidate_total,
                    f"Backtested {candidate_index} of {candidate_total} candidate models.",
                )

    combined = combination.blend(
        results,
        frequency=frequency,
        confidence_level=payload.confidence_level,
    )
    if combined is not None:
        results.append(combined.result)
    timings.record(Stage.FIT, time.perf_counter() - fit_started)

    for kind, status in unavailable_models().items():
        # The user-facing half only. The operator half is logged once per
        # process by the probe itself, where somebody can act on it.
        results.append(BacktestResult(model=kind, failed=True, failure_reason=status.reason))

    cps = payload.model_options.get("complexity_penalty_scale") if payload.model_options else None
    # model_options round-trips through stored JSON, so the value is only a number
    # if whoever wrote it put one there.
    penalty_scale = (
        float(cps) if isinstance(cps, int | float) and not isinstance(cps, bool) else None
    )
    selection = select_model(
        results,
        metric_weights=scoring_weights,
        n_observations=int(values.size),
        complexity_penalty_scale=penalty_scale,
    )
    if selection.winner is None:
        raise InsufficientDataError(
            "No candidate model could be fitted to this series. "
            + (fallback_reason or "Check that the target column contains numeric values.")
        )

    winner_kind = selection.winner.result.model
    if progress_callback is not None:
        progress_callback(
            "fitting",
            0,
            1,
            f"Fitting {winner_kind.value.replace('_', ' ')} on the full history...",
        )
    final_model: Forecaster
    if winner_kind is ModelKind.ENSEMBLE and combined is not None:
        final_model = EnsembleForecaster(
            frequency, profile, members=combined.members, weights=combined.weights
        )
    else:
        final_model = _make_factory(
            winner_kind,
            frequency,
            model_options,
            source,
            feature_cache,
        )(values, periods)

    try:
        final_model.fit(values, periods)
    except Exception as exc:
        logger.warning("Winner %s failed final refit (%s); using naive.", winner_kind, exc)
        used_fallback = True
        fallback_reason = (
            f"{winner_kind.value} won the backtest but failed to fit the full history "
            f"({type(exc).__name__}: {exc}). Fell back to a naive baseline."
        )
        winner_kind = ModelKind.NAIVE
        final_model = build_candidate(winner_kind, frequency, model_options, profile)
        final_model.fit(values, periods)

    # The backtest recorded whatever the *last* fold happened to configure,
    # and the model that gets shipped is the one refitted on the whole
    # history — a different search over more data. Reporting the fold's
    # settings beside the shipped forecast describes a model nobody has.
    winner_params = dict(final_model.params)
    if winner_params:
        selection.winner.result.params = winner_params

    if progress_callback is not None:
        progress_callback("fitting", 1, 1, "Selected model fitted; preparing results...")

    if progress_callback is not None:
        progress_callback("building_outputs", 0, 1, "Building intervals and segment forecasts...")

    forecast_index = future_periods(periods[-1], horizon, frequency)
    with timings.measure(Stage.PREDICT):
        point_forecast = np.asarray(
            final_model.predict(horizon, forecast_index), dtype=float
        ).ravel()[:horizon]

    if not np.all(np.isfinite(point_forecast)):
        last_finite = values[np.isfinite(values)]
        filler = float(last_finite[-1]) if last_finite.size else 0.0
        point_forecast = np.where(np.isfinite(point_forecast), point_forecast, filler)

    winner_result = selection.winner.result
    non_negative = bool(np.all(values[np.isfinite(values)] >= 0))
    with timings.measure(Stage.CALIBRATE):
        bands: IntervalBands = build_intervals(
            point_forecast,
            winner_result,
            confidence_level=payload.confidence_level,
            history=values,
            non_negative=non_negative,
        )
        interval_check = _interval_check(
            winner_result,
            point_forecast,
            bands,
            payload.confidence_level,
        )

    metrics = {
        "mae": winner_result.mae,
        "rmse": winner_result.rmse,
        "smape": winner_result.smape,
        "wmape": winner_result.wmape,
        "mase": winner_result.mase,
        "accuracy": accuracy_from_wmape(winner_result.wmape),
        "forecast_total": float(np.sum(point_forecast)),
        "best_case_total": float(np.sum(bands.best_case)),
        "worst_case_total": float(np.sum(bands.worst_case)),
        "history_total": float(np.nansum(values)),
        "backtest_folds": float(winner_result.n_folds),
        "seasonal_period": float(profile.seasonal_period),
        "seasonal_strength": round(profile.seasonal_strength * 100.0, 2),
        # What the chosen model was worth over the best baseline that ran
        # beside it. Negative means the baseline should have shipped, which is
        # the answer this exists to be able to give.
        "forecast_value_add": _value_add(results, winner_result),
    }

    fitted = _in_sample_fit(values, final_model, winner_kind, profile)

    changepoints = detect_changepoints(values)
    changepoint_note = _changepoint_note(changepoints, periods, len(values)) if changepoints else ""

    drivers = decompose_drivers(
        values,
        point_forecast,
        frequency,
        quantity=np.asarray(payload.quantity, dtype=float) if payload.quantity else None,
    )

    regions = _forecast_segments(
        payload.regions,
        point_forecast,
        winner_result,
        frequency,
        horizon,
        payload.max_folds,
        payload.confidence_level,
        payload.preparation,
    )
    categories = _forecast_segments(
        payload.categories,
        point_forecast,
        winner_result,
        frequency,
        horizon,
        payload.max_folds,
        payload.confidence_level,
        payload.preparation,
    )

    if progress_callback is not None:
        progress_callback("building_outputs", 1, 1, "Forecast outputs are ready to store.")

    leading = _columns_used(final_model, panel)
    rationale = (
        selection.rationale if not used_fallback else f"{fallback_reason} {selection.rationale}"
    )
    lead_sentence = describe(leading, frequency, payload.target_label)
    if lead_sentence:
        rationale = f"{rationale} {lead_sentence}"
    if changepoint_note:
        rationale = f"{rationale} {changepoint_note}"

    return ForecastOutput(
        leading_columns=leading,
        selected_model=winner_kind,
        selection_rationale=rationale,
        scoring_rule=selection.scoring_rule,
        used_fallback=used_fallback,
        fallback_reason=fallback_reason,
        history_periods=periods,
        history_values=[float(v) for v in values],
        fitted_values=fitted,
        forecast_periods=forecast_index,
        point_forecast=[float(v) for v in point_forecast],
        lower_bound=[float(v) for v in bands.lower],
        upper_bound=[float(v) for v in bands.upper],
        best_case=[float(v) for v in bands.best_case],
        base_case=[float(v) for v in bands.base_case],
        worst_case=[float(v) for v in bands.worst_case],
        metrics=metrics,
        candidates=[_candidate_row(c) for c in selection.candidates],
        interval_method=bands.method,
        diagnostics={
            **profile.as_dict(),
            "backtest_scheme": plan.scheme,
            "folds": plan.n_folds,
            "requested_horizon": horizon,
            "validated_horizon": plan.horizon,
            "changepoints": [periods[index].isoformat() for index in changepoints],
            "quality": payload.quality,
            # Which models this series was allowed to reach, and whether a
            # single number is a defensible thing to show for it. A lumpy
            # series gets quantiles and no point-accuracy claim, and the UI
            # needs to be told that rather than inferring it.
            "routing": route(profile).as_dict(),
            "timings": timings.as_dict(),
            "interval_check": interval_check,
        },
        regions=regions,
        categories=categories,
        drivers=drivers,
        timings=timings,
    )


def _held_out(winner: BacktestResult) -> list[HeldOutPoint]:
    return [
        HeldOutPoint(horizon=step, actual=float(actual), predicted=float(predicted))
        for fold in winner.folds
        for step, actual, predicted in zip(fold.steps(), fold.y_true, fold.y_pred, strict=False)
        if np.isfinite(actual) and np.isfinite(predicted)
    ]


def _interval_check(
    winner: BacktestResult,
    point_forecast: FloatArray,
    bands: IntervalBands,
    confidence_level: float,
) -> dict[str, object]:
    points = _held_out(winner)
    if not points:
        return {"measured": False, "reason": "No held-out fold produced a comparable pair."}

    lower = np.asarray(bands.lower, dtype=float)
    upper = np.asarray(bands.upper, dtype=float)
    reach = lower.size
    if reach == 0:
        return {"measured": False, "reason": "This run published no interval to check."}

    # A band floored at zero no longer carries an offset that means anything
    # away from its own point forecast, so those steps are skipped rather than
    # transferred onto a fold and counted as a miss.
    clipped = (lower <= 0.0) & (point_forecast > 0.0)
    below = lower - point_forecast
    above = upper - point_forecast

    transferable = [
        (point, min(point.horizon, reach) - 1)
        for point in points
        if not clipped[min(point.horizon, reach) - 1]
    ]
    transferred = [
        Interval(
            horizon=point.horizon,
            actual=point.actual,
            lower=point.predicted + float(below[step]),
            upper=point.predicted + float(above[step]),
        )
        for point, step in transferable
    ]
    served = realised_coverage(transferred, confidence_level)
    # A run affords a handful of origins, so no single horizon reaches the
    # sample floor and every per-horizon share reads as unmeasurable. Pooling
    # the steps gives one figure the evidence does support, which is the
    # difference between reporting nothing and reporting what is known.
    pooled = realised_coverage(
        (
            Interval(horizon=1, actual=one.actual, lower=one.lower, upper=one.upper)
            for one in transferred
        ),
        confidence_level,
    )
    repaired = calibrate(points, confidence_level)
    # Pooled conformal is fitted on the pooled residuals, not handed the widest
    # per-horizon width: that width was chosen to cover the longest step and
    # over-covers everything shorter, so quoting it as an overall figure
    # reports the band as far safer than it is.
    flattened = [HeldOutPoint(horizon=1, actual=p.actual, predicted=p.predicted) for p in points]
    repaired_pooled = measure_coverage(
        flattened, conformal_halfwidths(flattened, confidence_level), confidence_level
    )

    at_all = pooled.points[0] if pooled.points else None

    return {
        "measured": True,
        "nominal": round(confidence_level, 4),
        "steps_skipped_at_zero": int(clipped.sum()),
        "served": served.as_dict(),
        "served_holds": served.holds,
        "served_worst_gap_pp": _finite_or_none(served.worst_gap_pp),
        "served_pooled": round(at_all.observed, 4) if at_all else None,
        "served_pooled_observations": at_all.n_observations if at_all else 0,
        "served_pooled_holds": pooled.holds,
        "served_pooled_gap_pp": _finite_or_none(pooled.worst_gap_pp),
        "conformal_halfwidths": {
            str(h): round(w, 6) for h, w in sorted(repaired.halfwidths.items())
        },
        "conformal_worst_gap_pp": _finite_or_none(repaired.after.worst_gap_pp),
        "conformal_pooled_gap_pp": _finite_or_none(repaired_pooled.worst_gap_pp),
    }


def _finite_or_none(value: float) -> float | None:
    return None if not np.isfinite(value) else round(float(value), 2)


def _value_add(results: list[BacktestResult], winner: BacktestResult) -> float:
    """The winner's improvement over the strongest baseline, in percent.

    Measured on wMAPE where both have one, and on MAE otherwise so that a
    series whose validation windows total zero still gets an answer. Returns
    NaN when no baseline was scoreable — an unmeasured comparison is not a
    zero-value one.
    """
    baselines = [
        result
        for result in results
        if result.model in BASELINE_MODELS and result is not winner and not result.failed
    ]
    if not baselines:
        return float("nan")

    for metric in ("wmape", "mase", "mae"):
        model_error = float(getattr(winner, metric, float("nan")))
        candidates = [float(getattr(base, metric, float("nan"))) for base in baselines]
        usable = [value for value in candidates if np.isfinite(value)]
        if np.isfinite(model_error) and usable:
            return forecast_value_add(model_error, min(usable))

    return float("nan")


#: A level shift closer to the end of the history than this leaves too little
#: of the new regime to fit on, which is worth saying out loud.
RECENT_CHANGEPOINT_SHARE = 0.25


def _changepoint_note(changepoints: list[int], periods: list[date], n: int) -> str:
    """Say when the series changed level, because the fit cannot show it.

    A model fitted across a step change splits the difference: it sits above
    the new regime and below the old one, and every metric averages the two.
    Nothing in the accuracy figure distinguishes that from ordinary noise, so
    the dates are named and the recent ones are called out.
    """
    latest = changepoints[-1]
    when = ", ".join(periods[index].isoformat() for index in changepoints[-3:])
    if latest >= n * (1.0 - RECENT_CHANGEPOINT_SHARE):
        return (
            f"The series changed level at {when}, with only {n - latest} period(s) since — "
            "the fit still carries the earlier regime, so treat the forecast as provisional "
            "until more of the new one has been recorded."
        )
    return f"The series changed level at {when}, which the fit spans."


def _fallback_reason(
    n_observations: int,
    floor: int,
    frequency: ForecastFrequency,
    n_folds: int,
    profile: SeriesProfile,
) -> str:
    season = (
        f"a {profile.seasonal_period}-period season was detected"
        if profile.has_seasonality
        else "no repeating season was detected"
    )
    return (
        f"Only {n_observations} periods of history at {frequency.value} frequency "
        f"({floor} needed for full model selection, and {season})"
        + (", and no validation fold could be built" if n_folds == 0 else "")
        + ". Fell back to a seasonal-naive baseline, or naive where a full "
        "season is unavailable."
    )


def _candidate_row(scored: ScoredCandidate) -> CandidateRow:
    result = scored.result
    return {
        "model": result.model.value,
        "rank": scored.rank,
        "selected": scored.selected,
        "mae": _finite(result.mae),
        "rmse": _finite(result.rmse),
        "smape": _finite(result.smape),
        "wmape": _finite(result.wmape),
        "mase": _finite(result.mase),
        "winkler": _finite(result.winkler),
        "score": _finite(scored.score),
        "folds": result.n_folds,
        "fit_seconds": round(result.fit_seconds, 4),
        "params": result.params,
        "failed": result.failed,
        "failure_reason": result.failure_reason,
    }


def _finite(value: float) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None


def _in_sample_fit(
    values: FloatArray,
    model: Forecaster,
    kind: ModelKind,
    profile: SeriesProfile,
) -> list[float | None]:
    n = values.size
    fitted: list[float | None] = [None] * n

    if kind in (ModelKind.NAIVE, ModelKind.SEASONAL_NAIVE):
        period = profile.seasonal_period if kind is ModelKind.SEASONAL_NAIVE else 1
        period = max(1, min(period, n - 1))
        for index in range(period, n):
            fitted[index] = float(values[index - period])
        return fitted

    try:
        getter = getattr(model, "fitted_values", None)
        raw = (
            getter()
            if callable(getter)
            else getattr(getattr(model, "_fitted", None), "fittedvalues", None)
        )
        if raw is None:
            return fitted

        array = np.asarray(raw, dtype=float).ravel()
        for index in range(min(n, array.size)):
            if np.isfinite(array[index]):
                fitted[index] = float(array[index])
    except Exception:
        logger.debug("In-sample fit unavailable for %s", kind)

    return fitted


SEGMENT_CANDIDATES = (
    ModelKind.NAIVE,
    ModelKind.SEASONAL_NAIVE,
    ModelKind.THETA,
    ModelKind.HOLT_WINTERS,
    ModelKind.CROSTON,
)


TOO_LITTLE_HISTORY = "Too little history to validate a model."
UNFILLED_GAPS = "This series has periods with no data, and the run was asked not to fill them."
NO_CANDIDATE_HELD_UP = "No candidate model survived backtesting."
FINAL_FIT_FAILED = "The winning model could not be fitted over the full history."


@dataclass(slots=True)
class LeafFit:
    label: str
    forecast: list[float] | None = None
    lower: list[float] | None = None
    upper: list[float] | None = None
    model: ModelKind | None = None
    wmape: float | None = None
    mase: float | None = None
    folds: int = 0
    blocked_reason: str | None = None

    @property
    def fitted(self) -> bool:
        return self.forecast is not None

    @property
    def banded(self) -> bool:
        return self.lower is not None and self.upper is not None

    @property
    def accuracy(self) -> float | None:
        if self.wmape is None:
            return None
        value = accuracy_from_wmape(self.wmape)
        return round(float(value), 2) if np.isfinite(value) else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "forecast": self.forecast,
            "lower": self.lower,
            "upper": self.upper,
            "model": self.model.value if self.model else None,
            "wmape": self.wmape,
            "mase": self.mase,
            "folds": self.folds,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LeafFit:
        model = payload.get("model")
        wmape = payload.get("wmape")
        mase_value = payload.get("mase")

        def path(key: str) -> list[float] | None:
            value = payload.get(key)
            return [float(v) for v in value] if value is not None else None

        return cls(
            label=str(payload["label"]),
            forecast=path("forecast"),
            lower=path("lower"),
            upper=path("upper"),
            model=ModelKind(model) if model else None,
            wmape=float(wmape) if wmape is not None else None,
            mase=float(mase_value) if mase_value is not None else None,
            folds=int(payload.get("folds") or 0),
            blocked_reason=payload.get("blocked_reason"),
        )


def fit_leaf(
    label: str,
    periods: list[date],
    values: list[float],
    frequency: ForecastFrequency,
    horizon: int,
    max_folds: int | None,
    confidence_level: float,
    preparation: Preparation | None = None,
) -> LeafFit:
    try:
        return _fit_leaf(
            label, periods, values, frequency, horizon, max_folds, confidence_level, preparation
        )
    except Exception as exc:
        logger.warning("Series %s failed to fit: %s", label, exc)
        return LeafFit(label=label, blocked_reason=f"{type(exc).__name__}: {exc}")


def _fit_leaf(
    label: str,
    periods: list[date],
    values: list[float],
    frequency: ForecastFrequency,
    horizon: int,
    max_folds: int | None,
    confidence_level: float,
    preparation: Preparation | None = None,
) -> LeafFit:
    # A grouped series arrives with NaN wherever it has no row for a period,
    # and is prepared by the same rules as the total — the run asked for one
    # gap-fill policy, not one for the headline number and a silent zero-fill
    # for everything under it.
    prepare = preparation or Preparation()
    observed = np.asarray(values, dtype=float)
    history = prepare.apply(observed)
    calendar = list(periods)

    if history.size < 2 or history.size != len(calendar) or not np.any(np.isfinite(history)):
        return LeafFit(label=label, blocked_reason=TOO_LITTLE_HISTORY)
    if not np.all(np.isfinite(history)):
        return LeafFit(label=label, blocked_reason=UNFILLED_GAPS)

    profile = profile_series(history, frequency)
    plan = plan_backtest(
        history.size,
        horizon,
        frequency,
        max_folds=max_folds,
        seasonal_period=profile.seasonal_period,
    )
    if history.size < minimum_history(profile) or plan.n_folds == 0:
        return LeafFit(label=label, blocked_reason=TOO_LITTLE_HISTORY)

    results = [
        run_backtest(
            _make_factory(kind, frequency, None),
            kind,
            observed,
            calendar,
            plan,
            frequency,
            None,
            confidence_level,
            prepare=prepare,
        )
        for kind in SEGMENT_CANDIDATES
    ]

    selection = select_model(
        results,
        metric_weights=metric_weights_for(profile.intermittent),
        n_observations=int(history.size),
    )
    if selection.winner is None:
        return LeafFit(label=label, blocked_reason=NO_CANDIDATE_HELD_UP)

    kind = selection.winner.result.model
    try:
        model = _make_factory(kind, frequency, None)(history, calendar)
        model.fit(history, calendar)
        forecast = np.asarray(
            model.predict(horizon, future_periods(calendar[-1], horizon, frequency)),
            dtype=float,
        ).ravel()
    except Exception as exc:
        logger.debug("Series %s failed its final fit: %s", label, exc)
        return LeafFit(label=label, blocked_reason=f"{FINAL_FIT_FAILED} ({exc})")

    if forecast.size != horizon or not np.all(np.isfinite(forecast)):
        return LeafFit(label=label, blocked_reason=FINAL_FIT_FAILED)

    winning = selection.winner.result

    bands = build_intervals(
        forecast,
        winning,
        confidence_level,
        history=history,
        non_negative=bool(np.all(history >= 0)),
    )

    return LeafFit(
        label=label,
        forecast=[float(v) for v in forecast],
        lower=[float(v) for v in bands.lower],
        upper=[float(v) for v in bands.upper],
        model=kind,
        wmape=float(winning.wmape) if np.isfinite(winning.wmape) else None,
        mase=float(winning.mase) if np.isfinite(winning.mase) else None,
        folds=winning.n_folds,
    )


@dataclass(slots=True)
class SeriesResult:
    key: dict[str, str]
    label: str
    level: int
    parent_label: str | None
    forecast: list[float]
    model: ModelKind | None
    wmape: float | None
    mase: float | None
    accuracy: float | None
    accuracy_measured: bool
    folds: int
    forecast_total: float
    lower: list[float]
    upper: list[float]
    history: list[float]
    current_total: float
    prior_total: float | None
    share: float | None
    status: SeriesStatus
    blocked_reason: str | None = None


def forecast_grouped(
    leaves: list[SegmentInput],
    group_by: list[str],
    total_path: FloatArray,
    frequency: ForecastFrequency,
    horizon: int,
    max_folds: int | None,
    confidence_level: float = 0.8,
    preparation: Preparation | None = None,
) -> list[SeriesResult]:
    if not leaves:
        return []

    fits = [
        fit_leaf(
            leaf.label,
            leaf.periods,
            leaf.values,
            frequency,
            horizon,
            max_folds,
            confidence_level,
            preparation,
        )
        for leaf in leaves
    ]
    return assemble_grouped(leaves, fits, group_by, total_path)


def _shares(leaves: list[SegmentInput]) -> list[float] | None:
    """Each leaf's share of the whole, or None when there is no whole to divide.

    Taken from magnitude rather than from the signed total. A margin, a
    net-of-returns figure or a balance can sum to zero or below while every
    series under it is real, and dividing by that total gave a share of
    infinity — so the guard against it discarded the entire breakdown and the
    run came back with no grouped forecast at all and no reason why.
    """
    weights = [abs(leaf.current_total) for leaf in leaves]
    total = sum(weights)
    if total <= 0:
        # Every series is flat at zero over the comparison window. Nothing in
        # the data says one is bigger than another, so they share equally.
        return [1.0 / len(leaves)] * len(leaves) if leaves else None
    return [weight / total for weight in weights]


def assemble_grouped(
    leaves: list[SegmentInput],
    fits: list[LeafFit],
    group_by: list[str],
    total_path: FloatArray,
) -> list[SeriesResult]:
    if not leaves:
        return []

    shares = _shares(leaves)
    if shares is None:
        return []

    by_share = dict(zip((leaf.label for leaf in leaves), shares, strict=True))
    by_label = {leaf.label: leaf for leaf in leaves}
    fitted = {fit.label: fit for fit in fits if fit.fitted}
    blocked = {fit.label: fit.blocked_reason for fit in fits if not fit.fitted}

    total = np.asarray(total_path, dtype=float)
    root = build_tree(
        [
            (
                leaf.key,
                leaf.label,
                np.asarray(fitted[leaf.label].forecast, dtype=float)
                if leaf.label in fitted
                else total * by_share[leaf.label],
                by_share[leaf.label],
            )
            for leaf in leaves
        ],
        group_by,
    )
    reconcile_tree(root, total, non_negative=all_non_negative([leaf.values for leaf in leaves]))

    actuals = _roll_up_actuals(root, by_label)
    total_sum = float(np.sum(total))
    results: list[SeriesResult] = []

    for node in walk(root):
        path = node.reconciled if node.reconciled is not None else np.zeros(total.size)
        value = float(np.sum(path))
        past = actuals[node.label]
        fit = fitted.get(node.label)

        results.append(
            SeriesResult(
                key=node.key,
                label=node.label,
                level=node.level,
                parent_label=None,
                forecast=[float(v) for v in path],
                lower=_rescale_band(fit.lower, fit.forecast, path) if fit and fit.banded else [],
                upper=_rescale_band(fit.upper, fit.forecast, path) if fit and fit.banded else [],
                model=fit.model if fit else None,
                wmape=fit.wmape if fit else None,
                mase=fit.mase if fit else None,
                accuracy=fit.accuracy if fit else None,
                accuracy_measured=fit is not None,
                folds=fit.folds if fit else 0,
                forecast_total=round(value, 4),
                history=[float(v) for v in past.history],
                current_total=round(past.current, 4),
                prior_total=round(past.prior, 4) if past.prior is not None else None,
                share=round(value / total_sum * 100.0, 2) if total_sum else None,
                status=(
                    SeriesStatus.ESTIMATED
                    if node.is_leaf and node.label in blocked
                    else SeriesStatus.FORECAST
                ),
                blocked_reason=blocked.get(node.label),
            )
        )

    _attach_parents(root, results)
    return results


@dataclass(slots=True)
class _Actuals:
    current: float
    prior: float | None
    history: FloatArray


#: How far reconciliation may move a series before its interval stops meaning
#: anything. The band was measured around the series' own forecast; stretched
#: to fit a path twice the size, or one of the opposite sign, it is no longer
#: a measurement of anything and showing it as one is worse than showing none.
MAX_RECONCILIATION_STRETCH = 2.0


def _rescale_band(
    bound: list[float] | None,
    fitted: list[float] | None,
    reconciled: FloatArray,
) -> list[float]:
    """Carry a leaf's interval onto its reconciled path.

    Proportional, which is an approximation: the exact answer needs the
    covariance between the series, and nothing here has it. It holds while the
    reconciliation is a modest adjustment, which is the case it is for — a
    coherence correction, not a rewrite. Past that the band is dropped rather
    than stretched, because an interval nobody measured is not improved by
    being drawn.
    """
    if bound is None or fitted is None:
        return []

    band = np.asarray(bound, dtype=float)
    point = np.asarray(fitted, dtype=float)
    target = np.asarray(reconciled, dtype=float)

    if band.size != point.size or point.size != target.size:
        return []

    reference = float(np.max(np.abs(point))) if point.size else 0.0
    if reference <= 0.0:
        return []

    own, coherent = float(np.sum(point)), float(np.sum(target))
    if own != 0.0:
        stretch = coherent / own
        if stretch <= 0.0 or stretch > MAX_RECONCILIATION_STRETCH:
            return []

    usable = np.abs(point) > reference * SCALABLE_FRACTION
    scale = np.where(usable, np.divide(target, np.where(usable, point, 1.0)), 1.0)
    offset = (band - point) * scale

    return [float(v) for v in target + offset]


def _roll_up_actuals(root: Node, leaves: dict[str, SegmentInput]) -> dict[str, _Actuals]:
    totals: dict[str, _Actuals] = {}

    def visit(node: Node) -> _Actuals:
        if node.is_leaf:
            leaf = leaves.get(node.label)
            measured = (
                _Actuals(leaf.current_total, leaf.prior_total, np.asarray(leaf.values, dtype=float))
                if leaf
                else _Actuals(0.0, None, np.zeros(0))
            )
        else:
            parts = [visit(child) for child in node.children]
            priors = [part.prior for part in parts if part.prior is not None]
            measured = _Actuals(
                current=sum(part.current for part in parts),
                prior=sum(priors) if priors else None,
                history=_sum_histories([part.history for part in parts]),
            )

        totals[node.label] = measured
        return measured

    visit(root)
    return totals


def _sum_histories(histories: list[FloatArray]) -> FloatArray:
    """Roll children up into their parent, over the periods they reported.

    A period no child reported stays unreported rather than becoming a zero —
    the parent did not observe nothing there, it observed nothing at all.
    """
    usable = [history for history in histories if history.size]
    if not usable:
        return np.zeros(0)

    length = usable[0].size
    aligned = [history for history in usable if history.size == length]
    if not aligned:
        return np.zeros(0)

    stacked = np.vstack(aligned)
    rolled = np.nansum(stacked, axis=0)
    return np.where(np.all(np.isnan(stacked), axis=0), np.nan, rolled)


def _attach_parents(root: Node, results: list[SeriesResult]) -> None:
    by_label = {result.label: result for result in results}

    def visit(node: Node, parent_label: str | None) -> None:
        row = by_label.get(node.label)
        if row is not None:
            row.parent_label = parent_label
        for child in node.children:
            visit(child, node.label)

    visit(root, None)


def _forecast_segments(
    segments: list[SegmentInput],
    total_path: FloatArray,
    winner: BacktestResult,
    frequency: ForecastFrequency,
    horizon: int,
    max_folds: int | None,
    confidence_level: float,
    preparation: Preparation | None = None,
) -> list[SegmentOutput]:
    if not segments:
        return []

    shares = _shares(segments)
    if shares is None:
        return []

    total_forecast = float(np.sum(total_path))

    attempted = [
        fit_leaf(
            s.label,
            s.periods,
            s.values,
            frequency,
            horizon,
            max_folds,
            confidence_level,
            preparation,
        )
        for s in segments
    ]
    fits = {fit.label: fit for fit in attempted if fit.fitted}

    paths = [
        np.asarray(fits[segment.label].forecast, dtype=float)
        if segment.label in fits
        else np.asarray(total_path, dtype=float) * share
        for segment, share in zip(segments, shares, strict=True)
    ]
    reconciled = reconcile_to_total(
        paths,
        np.asarray(total_path, dtype=float),
        shares,
        non_negative=all_non_negative([segment.values for segment in segments]),
    )

    if fits:
        gap = coherence_gap(
            [np.asarray(fit.forecast, dtype=float) for fit in fits.values()],
            np.asarray(total_path, dtype=float),
        )
        if gap > 0.25:
            logger.info(
                "Segment forecasts imply a total %.0f%% away from the direct one; "
                "reconciled toward the direct total.",
                gap * 100,
            )

    inherited = accuracy_from_wmape(winner.wmape)

    out: list[SegmentOutput] = []
    for segment, path in zip(segments, reconciled, strict=True):
        change = None
        prior = segment.prior_total
        if prior:
            change = round((segment.current_total - prior) / abs(prior) * 100.0, 2)

        fit = fits.get(segment.label)
        if fit is not None:
            accuracy = fit.accuracy
        else:
            accuracy = round(float(inherited), 2) if np.isfinite(inherited) else None

        value = float(np.sum(path))
        out.append(
            SegmentOutput(
                label=segment.label,
                forecast_value=round(value, 4),
                prior_year_value=segment.prior_total,
                change_vs_last_year=change,
                accuracy=accuracy,
                share=round(value / total_forecast * 100.0, 2) if total_forecast else 0.0,
                model=fit.model.value if fit and fit.model else None,
                accuracy_measured=fit is not None,
            )
        )

    out.sort(key=lambda s: s.forecast_value, reverse=True)
    return out


def _stability(series: list[float]) -> float:
    array = np.asarray(series, dtype=float)
    finite = array[np.isfinite(array)]
    if finite.size < 3:
        return float("nan")
    mean = float(np.mean(finite))
    std = float(np.std(finite))
    if mean == 0 or std == 0:
        return float("nan")
    return abs(mean) / std
