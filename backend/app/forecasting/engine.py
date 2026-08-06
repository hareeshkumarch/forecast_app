from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypedDict

import numpy as np
import numpy.typing as npt

from app.core.logging import get_logger
from app.forecasting import combination
from app.forecasting.backtest import BacktestResult, ModelFactory, plan_backtest, run_backtest
from app.forecasting.decomposition import Driver, decompose_drivers
from app.forecasting.diagnostics import SeriesProfile, minimum_history, profile_series
from app.forecasting.drivers import DriverLink, DriverPanel, build_panel, describe
from app.forecasting.frequency import future_periods
from app.forecasting.hierarchy import (
    Node,
    build_tree,
    coherence_gap,
    reconcile_to_total,
    reconcile_tree,
    walk,
)
from app.forecasting.metrics import accuracy_from_wmape
from app.forecasting.models import (
    EnsembleForecaster,
    Forecaster,
    build_candidate,
    build_candidates,
    unavailable_models,
)
from app.forecasting.scenarios import IntervalBands, build_intervals
from app.forecasting.selection import ScoredCandidate, metric_weights_for, select_model
from app.forecasting.transforms import TransformedForecaster, build_transform
from app.models.enums import ForecastFrequency, ModelKind, SeriesStatus

FloatArray = npt.NDArray[np.float64]

logger = get_logger(__name__)

#: A forecast period can carry a rescaled band when its own level is a
#: meaningful fraction of the largest the series reaches. Judged against the
#: series rather than against a fixed number, because an absolute floor means
#: one thing for revenue in millions and quite another for a conversion rate.
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
    #: The grouping columns that identify this leaf, when the run has a grain.
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
    #: Other numeric columns from the same upload, on the target's calendar.
    #: Candidates only — which of them, if any, a model ends up using is
    #: settled by the fit, not by the caller.
    drivers: dict[str, list[float]] = field(default_factory=dict)
    #: What the target is called, so an explanation can name it.
    target_label: str = "the total"


@dataclass(slots=True)
class SegmentOutput:
    label: str
    forecast_value: float
    prior_year_value: float | None
    change_vs_last_year: float | None
    accuracy: float | None
    share: float
    model: str | None = None
    """True when the accuracy came from this segment's own backtest rather
    than being inherited from the top line."""
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

    regions: list[SegmentOutput] = field(default_factory=list)
    categories: list[SegmentOutput] = field(default_factory=list)
    drivers: list[Driver] = field(default_factory=list)
    #: Columns of the customer's own data the winning model actually used, and
    #: how far ahead each one leads. Empty when none earned their place, which
    #: is a real answer and worth showing.
    leading_columns: list[DriverLink] = field(default_factory=list)


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
    drivers: DriverPanel | None = None,
) -> ModelFactory:
    def factory(y_train: FloatArray, _periods_train: list[date]) -> Forecaster:
        window_profile = profile_series(y_train, frequency)
        # The panel spans the whole series, and every fold is a prefix of it.
        # A driver's lag is at least the horizon, so the furthest back any row
        # can reach is inside its own training window — the fold cannot see
        # past its cut, which is what makes the backtest number honest.
        model = build_candidate(kind, frequency, options, window_profile, drivers)
        if kind in TRANSFORMABLE:
            return TransformedForecaster(model, build_transform(y_train, window_profile))
        return model

    return factory


def _columns_used(model: Forecaster, panel: DriverPanel) -> list[DriverLink]:
    """
    Which of the offered columns the fitted model kept.

    Asked of the model rather than assumed from the panel: the panel is what
    was offered, and both models that can take drivers are free to decide the
    series forecasts better without them. Reporting the offer as though it were
    the decision would be the more flattering answer and the wrong one.
    """
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

    # Other numeric columns from the same upload, screened for the ones that
    # move before the target does. Screening only earns them a place in the
    # design matrix; the models decide out of sample whether to use them, and
    # a dataset with nothing leading anything gets an empty panel and the
    # forecast it would have had.
    panel = build_panel(
        values,
        {name: np.asarray(column, dtype=float) for name, column in payload.drivers.items()},
        horizon=horizon,
        frequency=frequency,
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
                payload.model_options,
                profile,
            )
        ]
    else:
        candidates = build_candidates(frequency, payload.model_options, profile, panel)

    results: list[BacktestResult] = []
    candidate_total = len(candidates)
    for candidate_index, candidate in enumerate(candidates, start=1):
        kind = candidate.kind
        if progress_callback is not None:
            progress_callback(
                "backtesting",
                candidate_index - 1,
                candidate_total,
                f"Backtesting {kind.value.replace('_', ' ')} ({candidate_index} of {candidate_total})...",
            )
        results.append(
            run_backtest(
                _make_factory(kind, frequency, payload.model_options, panel),
                kind,
                values,
                periods,
                plan,
                frequency,
                weights,
                payload.confidence_level,
            )
        )
        if progress_callback is not None:
            progress_callback(
                "backtesting",
                candidate_index,
                candidate_total,
                f"Backtested {candidate_index} of {candidate_total} candidate models.",
            )

    # The combination is built from the folds the candidates have just run, so
    # it competes on exactly the history they were judged on without anything
    # being refitted. It stands down when it cannot beat its own best member.
    combined = combination.blend(
        results,
        frequency=frequency,
        confidence_level=payload.confidence_level,
        weights=weights,
    )
    if combined is not None:
        results.append(combined.result)

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
    if progress_callback is not None:
        progress_callback(
            "fitting",
            0,
            1,
            f"Fitting {winner_kind.value.replace('_', ' ')} on the full history...",
        )
    if winner_kind is ModelKind.ENSEMBLE and combined is not None:
        # Only the blend knows who is in it and what say each of them has.
        final_model = EnsembleForecaster(
            frequency, profile, members=combined.members, weights=combined.weights
        )
    else:
        final_model = _make_factory(winner_kind, frequency, payload.model_options, panel)(
            values, periods
        )

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

    if progress_callback is not None:
        progress_callback("fitting", 1, 1, "Selected model fitted; preparing results...")

    if progress_callback is not None:
        progress_callback("building_outputs", 0, 1, "Building intervals and segment forecasts...")

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
        # Against the free forecast, so a series whose wMAPE has to give up
        # still reports something rather than a dash and nothing else.
        "mase": winner_result.mase,
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

    regions = _forecast_segments(
        payload.regions,
        point_forecast,
        winner_result,
        frequency,
        horizon,
        payload.max_folds,
        payload.confidence_level,
    )
    categories = _forecast_segments(
        payload.categories,
        point_forecast,
        winner_result,
        frequency,
        horizon,
        payload.max_folds,
        payload.confidence_level,
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


# Fitting the full roster for every segment would multiply the run's cost by
# the number of segments for very little gain: a segment carries less signal
# than the total it came from, so the expensive candidates rarely win and often
# overfit. These cover level, trend, seasonality and intermittency.
SEGMENT_CANDIDATES = (
    ModelKind.NAIVE,
    ModelKind.SEASONAL_NAIVE,
    ModelKind.THETA,
    ModelKind.HOLT_WINTERS,
    ModelKind.CROSTON,
)


TOO_LITTLE_HISTORY = "Too little history to validate a model."
NO_CANDIDATE_HELD_UP = "No candidate model survived backtesting."
FINAL_FIT_FAILED = "The winning model could not be fitted over the full history."


@dataclass(slots=True)
class LeafFit:
    """
    One series' own model, or the reason it has none.

    This is the unit of parallelism in a grouped run, so it has to survive a
    trip through a message broker: everything on it is JSON, and a fit that did
    not happen carries its reason rather than being absent.
    """

    label: str
    forecast: list[float] | None = None
    #: This series' own prediction interval, from its own backtest residuals.
    #: Absent when nothing could be measured — an inherited band would claim a
    #: precision this series never demonstrated.
    lower: list[float] | None = None
    upper: list[float] | None = None
    model: ModelKind | None = None
    wmape: float | None = None
    #: Error against the seasonal-naive benchmark. Carried alongside wMAPE
    #: because an intermittent leaf routinely has no usable wMAPE at all.
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
        """The accuracy the measured error implies, or None if nothing was measured."""
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
) -> LeafFit:
    """
    Runs the same select-and-backtest pipeline the top line gets, over a
    cheaper roster.

    Takes a labelled history rather than a segment because that is all a fit
    reads, and because in a grouped run this is what crosses the wire.

    Never raises. A series that cannot be validated is apportioned from its
    parent instead, and one unfittable series must not take the run with it.
    """
    try:
        return _fit_leaf(label, periods, values, frequency, horizon, max_folds, confidence_level)
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
) -> LeafFit:
    history = np.asarray(values, dtype=float)
    calendar = list(periods)

    if history.size < 2 or history.size != len(calendar) or not np.any(np.isfinite(history)):
        return LeafFit(label=label, blocked_reason=TOO_LITTLE_HISTORY)

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
            history,
            calendar,
            plan,
            frequency,
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

    # The same interval machinery the top line uses, on this series' own
    # residuals. A series never fitted gets no band at all rather than an
    # inherited one, which would claim a precision it never demonstrated.
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
    """One series in a grouped run, as the service needs to persist it."""

    key: dict[str, str]
    label: str
    level: int
    parent_label: str | None
    forecast: list[float]
    model: ModelKind | None
    wmape: float | None
    #: The scale-free counterpart, for series where wMAPE cannot be computed.
    mase: float | None
    accuracy: float | None
    accuracy_measured: bool
    folds: int
    forecast_total: float
    #: Reconciled alongside the point forecast, so the band keeps the width its
    #: own backtest earned rather than the one it had before scaling. Empty
    #: where the series was apportioned and never measured.
    lower: list[float]
    upper: list[float]
    #: This series' own actuals over the shared calendar. Without them a chart
    #: scoped to one series shows a horizon floating on nothing.
    history: list[float]
    #: The last full window of actuals, and the one before it. Both cover the
    #: same span, so the change between them is a like-for-like trend — which
    #: the forecast total, covering only the horizon, would not be.
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
) -> list[SeriesResult]:
    """
    Fits every leaf here and assembles the tree from the results.

    The sequential path, for a single-node deployment and for the tests. A run
    with a broker fits the leaves in parallel and calls `assemble_grouped` with
    what comes back — the assembly is identical either way.
    """
    if not leaves:
        return []

    fits = [
        fit_leaf(
            leaf.label, leaf.periods, leaf.values, frequency, horizon, max_folds, confidence_level
        )
        for leaf in leaves
    ]
    return assemble_grouped(leaves, fits, group_by, total_path)


def assemble_grouped(
    leaves: list[SegmentInput],
    fits: list[LeafFit],
    group_by: list[str],
    total_path: FloatArray,
) -> list[SeriesResult]:
    """
    Assembles the levels the grouping implies from fits already produced, and
    reconciles the whole tree to the directly forecast total.

    A leaf that could not be fitted keeps its place in the tree and is
    apportioned instead, so the levels still add up and the row says where its
    number came from.
    """
    if not leaves:
        return []

    grand_total = sum(leaf.current_total for leaf in leaves)
    if grand_total <= 0:
        return []

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
                else total * (leaf.current_total / grand_total),
                leaf.current_total / grand_total,
            )
            for leaf in leaves
        ],
        group_by,
    )
    reconcile_tree(root, total)

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
    """A node's own history, and the two windows its trend is read from."""

    current: float
    prior: float | None
    history: FloatArray


def _rescale_band(
    bound: list[float] | None,
    fitted: list[float] | None,
    reconciled: FloatArray,
) -> list[float]:
    """
    Moves a band onto the reconciled path it now belongs to.

    Reconciliation multiplies a series' level, so a band left at its original
    height would sit beside the line instead of around it. The relative width
    is what the backtest actually measured, so that is what is preserved.

    A period the model forecast as zero has no ratio to scale by — there the
    offset is carried across unchanged, which is the only reading that does
    not either vanish or explode.
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
        # The model forecast nothing at all; a band around it would be invented.
        return []

    usable = np.abs(point) > reference * SCALABLE_FRACTION
    scale = np.where(usable, np.divide(target, np.where(usable, point, 1.0)), 1.0)
    offset = (band - point) * scale

    return [float(v) for v in target + offset]


def _roll_up_actuals(root: Node, leaves: dict[str, SegmentInput]) -> dict[str, _Actuals]:
    """
    Each node's history, summed up from the leaves beneath it.

    A parent has no series of its own to read this from, but it is exactly the
    sum of its children's — every leaf shares one calendar, which is what makes
    the addition meaningful — so it is carried up rather than leaving every
    level above the grain without a past.
    """
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
    """Adds children's histories, ignoring any that does not share the calendar."""
    usable = [history for history in histories if history.size]
    if not usable:
        return np.zeros(0)

    length = usable[0].size
    aligned = [history for history in usable if history.size == length]
    return np.sum(aligned, axis=0) if aligned else np.zeros(0)


def _attach_parents(root: Node, results: list[SeriesResult]) -> None:
    """Second pass: each result learns its parent's label, so the service can link rows."""
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
) -> list[SegmentOutput]:
    """
    Forecasts every segment in its own right, then reconciles the results to
    the top line.

    The old behaviour multiplied the total by a share frozen at run time, so
    two segments moving in opposite directions produced identical curves that
    differed only in height, and every segment reported the top line's accuracy
    as though it were its own. Each segment now has its own model, its own
    backtest and its own measured error; only segments too short to validate
    fall back to apportioning, and those say so.
    """
    if not segments:
        return []

    grand_total = sum(s.current_total for s in segments)
    if grand_total <= 0:
        return []

    total_forecast = float(np.sum(total_path))
    shares = [s.current_total / grand_total for s in segments]

    attempted = [
        fit_leaf(s.label, s.periods, s.values, frequency, horizon, max_folds, confidence_level)
        for s in segments
    ]
    fits = {fit.label: fit for fit in attempted if fit.fitted}

    # Reconciliation needs a path per segment: a real forecast where there is
    # one, the apportioned share everywhere else.
    paths = [
        np.asarray(fits[segment.label].forecast, dtype=float)
        if segment.label in fits
        else np.asarray(total_path, dtype=float) * share
        for segment, share in zip(segments, shares, strict=True)
    ]
    reconciled = reconcile_to_total(paths, np.asarray(total_path, dtype=float), shares)

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
