from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TypedDict

import numpy as np
import numpy.typing as npt

from app.core.logging import get_logger
from app.forecasting.backtest import BacktestResult, ModelFactory, plan_backtest, run_backtest
from app.forecasting.decomposition import Driver, decompose_drivers
from app.forecasting.diagnostics import SeriesProfile, minimum_history, profile_series
from app.forecasting.frequency import future_periods
from app.forecasting.metrics import accuracy_from_wmape
from app.forecasting.models import (
    Forecaster,
    build_candidate,
    build_candidates,
    unavailable_models,
)
from app.forecasting.scenarios import IntervalBands, build_intervals
from app.forecasting.selection import ScoredCandidate, metric_weights_for, select_model
from app.forecasting.transforms import TransformedForecaster, build_transform
from app.models.enums import ForecastFrequency, ModelKind

FloatArray = npt.NDArray[np.float64]

logger = get_logger(__name__)


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


@dataclass(slots=True)
class SegmentOutput:
    label: str
    forecast_value: float
    prior_year_value: float | None
    change_vs_last_year: float | None
    accuracy: float | None
    share: float


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

    regions: list[SegmentOutput] = field(default_factory=list)
    categories: list[SegmentOutput] = field(default_factory=list)
    drivers: list[Driver] = field(default_factory=list)


class CandidateRow(TypedDict):
    model: str
    rank: int
    selected: bool
    mae: float | None
    rmse: float | None
    smape: float | None
    wmape: float | None
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


def _make_factory(
    kind: ModelKind,
    frequency: ForecastFrequency,
    options: dict[str, object] | None,
) -> ModelFactory:
    def factory(y_train: FloatArray, _periods_train: list[date]) -> Forecaster:
        window_profile = profile_series(y_train, frequency)
        model = build_candidate(kind, frequency, options, window_profile)
        if kind in TRANSFORMABLE:
            return TransformedForecaster(model, build_transform(y_train, window_profile))
        return model

    return factory


def run_forecast(payload: ForecastInput) -> ForecastOutput:
    values = np.asarray(payload.series.values, dtype=float)
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

    profile = profile_series(values, frequency)
    floor = minimum_history(profile)

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
                payload.model_options,
                profile,
            )
        ]
    else:
        candidates = build_candidates(frequency, payload.model_options, profile)

    results: list[BacktestResult] = []
    for candidate in candidates:
        kind = candidate.kind
        results.append(
            run_backtest(
                _make_factory(kind, frequency, payload.model_options),
                kind,
                values,
                periods,
                plan,
                frequency,
                weights,
            )
        )

    for kind, reason in unavailable_models().items():
        results.append(BacktestResult(model=kind, failed=True, failure_reason=reason))

    selection = select_model(
        results,
        metric_weights=payload.metric_weights or metric_weights_for(profile.intermittent),
        n_observations=int(values.size),
    )
    if selection.winner is None:
        raise InsufficientDataError(
            "No candidate model could be fitted to this series. "
            + (fallback_reason or "Check that the target column contains numeric values.")
        )

    winner_kind = selection.winner.result.model
    final_model = _make_factory(winner_kind, frequency, payload.model_options)(values, periods)

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
        final_model = build_candidate(winner_kind, frequency, payload.model_options, profile)
        final_model.fit(values, periods)

    forecast_index = future_periods(periods[-1], horizon, frequency)
    point_forecast = np.asarray(final_model.predict(horizon, forecast_index), dtype=float).ravel()[
        :horizon
    ]

    if not np.all(np.isfinite(point_forecast)):
        last_finite = values[np.isfinite(values)]
        filler = float(last_finite[-1]) if last_finite.size else 0.0
        point_forecast = np.where(np.isfinite(point_forecast), point_forecast, filler)

    winner_result = selection.winner.result
    non_negative = bool(np.all(values[np.isfinite(values)] >= 0))
    bands: IntervalBands = build_intervals(
        point_forecast,
        winner_result,
        confidence_level=payload.confidence_level,
        history=values,
        non_negative=non_negative,
    )

    metrics = {
        "mae": winner_result.mae,
        "rmse": winner_result.rmse,
        "smape": winner_result.smape,
        "wmape": winner_result.wmape,
        "accuracy": accuracy_from_wmape(winner_result.wmape),
        "forecast_total": float(np.sum(point_forecast)),
        "best_case_total": float(np.sum(bands.best_case)),
        "worst_case_total": float(np.sum(bands.worst_case)),
        "history_total": float(np.nansum(values)),
        "backtest_folds": float(winner_result.n_folds),
        "seasonal_period": float(profile.seasonal_period),
        "seasonal_strength": round(profile.seasonal_strength * 100.0, 2),
    }

    fitted = _in_sample_fit(values, final_model, winner_kind, profile)

    drivers = decompose_drivers(
        values,
        point_forecast,
        frequency,
        quantity=np.asarray(payload.quantity, dtype=float) if payload.quantity else None,
    )

    total_forecast = float(np.sum(point_forecast))
    regions = _project_segments(payload.regions, total_forecast, winner_result)
    categories = _project_segments(payload.categories, total_forecast, winner_result)

    return ForecastOutput(
        selected_model=winner_kind,
        selection_rationale=(
            selection.rationale if not used_fallback else f"{fallback_reason} {selection.rationale}"
        ),
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
            "quality": payload.quality,
        },
        regions=regions,
        categories=categories,
        drivers=drivers,
    )


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


def _project_segments(
    segments: list[SegmentInput],
    total_forecast: float,
    winner: BacktestResult,
) -> list[SegmentOutput]:
    if not segments:
        return []

    grand_total = sum(s.current_total for s in segments)
    if grand_total <= 0:
        return []

    base_accuracy = accuracy_from_wmape(winner.wmape)
    stabilities = {s.label: _stability(s.series) for s in segments}

    finite_stabilities = [v for v in stabilities.values() if np.isfinite(v)]
    mean_stability = float(np.mean(finite_stabilities)) if finite_stabilities else 0.0

    out: list[SegmentOutput] = []
    for segment in segments:
        share = segment.current_total / grand_total
        forecast_value = total_forecast * share

        change = None
        prior = segment.prior_total
        if prior:
            change = round((segment.current_total - prior) / abs(prior) * 100.0, 2)

        accuracy: float | None = None
        if np.isfinite(base_accuracy):
            stability = stabilities[segment.label]
            adjustment = (
                float(np.clip((stability / mean_stability - 1.0) * 6.0, -8.0, 8.0))
                if np.isfinite(stability) and mean_stability
                else 0.0
            )
            accuracy = round(float(np.clip(base_accuracy + adjustment, 0.0, 99.9)), 2)

        out.append(
            SegmentOutput(
                label=segment.label,
                forecast_value=round(forecast_value, 4),
                prior_year_value=segment.prior_total,
                change_vs_last_year=change,
                accuracy=accuracy,
                share=round(share * 100.0, 2),
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
