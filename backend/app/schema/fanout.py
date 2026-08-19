from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.logging import get_logger
from app.forecasting.diagnostics import profile_series
from app.forecasting.engine import LeafFit, fit_leaf
from app.forecasting.frequency import future_periods, seasonal_period
from app.forecasting.models import build_candidate
from app.forecasting.preparation import Preparation
from app.forecasting.routing import INTERMITTENT, LUMPY, NO_DEMAND, route
from app.models.enums import ForecastFrequency, GapFill, IssueSeverity, ModelKind
from app.schema.canonical import assert_canonical
from app.schema.contract import DS, SERIES_ID, SERIES_KEY_SEPARATOR, Y
from app.schema.validation import (
    ROUTE_FALLBACK,
    ROUTE_MODEL,
    STATUS_REJECT,
    SeriesReport,
    ValidationReport,
    validate_canonical,
)

logger = get_logger(__name__)

FORECAST_COLUMNS = (SERIES_ID, DS, Y, "y_lower", "y_upper", "model", "route")
PARENT_LEVEL = "level"


class FanOutConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    frequency: ForecastFrequency
    horizon: int = Field(ge=1, le=365)
    max_workers: int = Field(default=settings.forecast_workers, ge=1, le=64)
    confidence_level: float = Field(default=0.8, gt=0.0, lt=1.0)
    max_folds: int | None = Field(default=None, ge=1, le=20)
    min_history: int | None = Field(default=None, ge=2)
    gap_fill: GapFill = GapFill.NONE
    winsorise_sigmas: float | None = Field(default=None, gt=0.0)
    hierarchy: list[str] = Field(default_factory=list)
    aggregate_to_parents: bool = False

    @property
    def preparation(self) -> Preparation:
        return Preparation(fill=self.gap_fill, winsorise_sigmas=self.winsorise_sigmas)


@dataclass(slots=True, frozen=True)
class SeriesError:
    series_id: str
    code: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {"series_id": self.series_id, "code": self.code, "detail": self.detail}


@dataclass(slots=True)
class FanOutResult:
    forecasts: pl.DataFrame
    parents: pl.DataFrame
    report: ValidationReport
    errors: list[SeriesError] = field(default_factory=list)
    models: dict[str, str] = field(default_factory=dict)

    @property
    def forecast_series_count(self) -> int:
        return int(self.forecasts[SERIES_ID].n_unique()) if self.forecasts.height else 0

    def as_dict(self) -> dict[str, object]:
        return {
            "series_forecast": self.forecast_series_count,
            "rows": self.forecasts.height,
            "parent_rows": self.parents.height,
            "errors": [error.as_dict() for error in self.errors],
            "models": dict(sorted(self.models.items())),
            "validation": self.report.as_dict(),
        }


def run_fanout(
    frame: pl.DataFrame,
    config: FanOutConfig,
    *,
    report: ValidationReport | None = None,
) -> FanOutResult:
    assert_canonical(frame)

    resolved = report or validate_canonical(
        frame, frequency=config.frequency, min_history=config.min_history
    )
    routes = {item.series_id: item for item in resolved.series}

    groups = [
        (str(series_id), group[DS].to_list(), group[Y].to_numpy().astype(float))
        for (series_id,), group in frame.group_by([SERIES_ID], maintain_order=True)
    ]
    fittable = [
        group
        for group in groups
        if routes.get(group[0]) and routes[group[0]].status != STATUS_REJECT
    ]

    errors = [_rejection(item) for item in resolved.series if item.status == STATUS_REJECT]

    rows: list[dict[str, object]] = []
    models: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        outcomes = pool.map(
            lambda group: _forecast_one(group, config, routes[group[0]].route), fittable
        )

        for series_id, points, model, taken, failure in outcomes:
            if failure is not None:
                errors.append(failure)
                continue
            models[series_id] = model
            rows.extend(
                {
                    SERIES_ID: series_id,
                    DS: period,
                    Y: point,
                    "y_lower": lower,
                    "y_upper": upper,
                    "model": model,
                    "route": taken,
                }
                for period, point, lower, upper in points
            )

    forecasts = _as_frame(rows)
    parents = (
        _bottom_up(forecasts, config.hierarchy)
        if config.aggregate_to_parents and config.hierarchy
        else _empty_parents()
    )

    return FanOutResult(
        forecasts=forecasts, parents=parents, report=resolved, errors=errors, models=models
    )


def _rejection(item: SeriesReport) -> SeriesError:
    blocking = next(
        (finding for finding in item.findings if finding.severity is IssueSeverity.SEVERE), None
    )
    return SeriesError(
        series_id=item.series_id,
        code=blocking.code if blocking else "rejected",
        detail=blocking.detail if blocking else "This series was rejected before fitting.",
    )


def _forecast_one(
    group: tuple[str, list[date], np.ndarray],
    config: FanOutConfig,
    taken: str,
) -> tuple[str, list[tuple[date, float, float | None, float | None]], str, str, SeriesError | None]:
    series_id, periods, values = group

    try:
        if taken == ROUTE_MODEL:
            fit = fit_leaf(
                series_id,
                periods,
                [float(value) for value in values],
                config.frequency,
                config.horizon,
                config.max_folds,
                config.confidence_level,
                config.preparation,
            )
            if fit.fitted:
                return series_id, _points(fit, periods, config), _model_name(fit), ROUTE_MODEL, None
            logger.info("Series %s fell back: %s", series_id, fit.blocked_reason)

        return (*_fallback(series_id, periods, values, config), ROUTE_FALLBACK, None)
    except Exception as exc:
        return (
            series_id,
            [],
            "",
            taken,
            SeriesError(
                series_id=series_id, code="fit_failed", detail=f"{type(exc).__name__}: {exc}"
            ),
        )


def _points(
    fit: LeafFit, periods: list[date], config: FanOutConfig
) -> list[tuple[date, float, float | None, float | None]]:
    horizon = future_periods(periods[-1], config.horizon, config.frequency)
    forecast = fit.forecast or []
    lower = fit.lower if fit.banded else [None] * len(forecast)
    upper = fit.upper if fit.banded else [None] * len(forecast)
    return [
        (period, float(point), _finite(low), _finite(high))
        for period, point, low, high in zip(horizon, forecast, lower, upper, strict=False)
    ]


def _fallback(
    series_id: str,
    periods: list[date],
    values: np.ndarray,
    config: FanOutConfig,
) -> tuple[str, list[tuple[date, float, float | None, float | None]], str]:
    history = config.preparation.apply(np.asarray(values, dtype=float))
    history = np.nan_to_num(history, nan=0.0, posinf=0.0, neginf=0.0)
    kind = fallback_kind(history, config.frequency)

    horizon = future_periods(periods[-1], config.horizon, config.frequency)
    model = build_candidate(kind, config.frequency, None, profile_series(history, config.frequency))
    model.fit(history, periods)
    forecast = np.asarray(model.predict(config.horizon, horizon), dtype=float).ravel()

    return (
        series_id,
        [
            (period, float(point), None, None)
            for period, point in zip(horizon, forecast, strict=False)
        ],
        kind.value,
    )


def fallback_kind(history: np.ndarray, frequency: ForecastFrequency) -> ModelKind:
    profile = profile_series(history, frequency)
    if route(profile).demand_class in (INTERMITTENT, LUMPY, NO_DEMAND):
        return ModelKind.CROSTON
    if history.size >= 2 * seasonal_period(frequency):
        return ModelKind.SEASONAL_NAIVE
    return ModelKind.NAIVE


def _model_name(fit: LeafFit) -> str:
    return fit.model.value if fit.model else ModelKind.NAIVE.value


def _finite(value: float | None) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None


def _as_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    schema = {
        SERIES_ID: pl.Utf8,
        DS: pl.Date,
        Y: pl.Float64,
        "y_lower": pl.Float64,
        "y_upper": pl.Float64,
        "model": pl.Utf8,
        "route": pl.Utf8,
    }
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(rows, schema=schema).sort([SERIES_ID, DS])


def _empty_parents() -> pl.DataFrame:
    return pl.DataFrame(
        schema={PARENT_LEVEL: pl.Int32, SERIES_ID: pl.Utf8, DS: pl.Date, Y: pl.Float64}
    )


def _bottom_up(forecasts: pl.DataFrame, hierarchy: list[str]) -> pl.DataFrame:
    if forecasts.height == 0 or len(hierarchy) < 2:
        return _empty_parents()

    parts = forecasts.with_columns(
        pl.col(SERIES_ID).str.split(SERIES_KEY_SEPARATOR).alias("_parts")
    )
    levels = [
        parts.with_columns(
            pl.col("_parts").list.head(depth).list.join(SERIES_KEY_SEPARATOR).alias(SERIES_ID),
            pl.lit(depth, dtype=pl.Int32).alias(PARENT_LEVEL),
        )
        .group_by([PARENT_LEVEL, SERIES_ID, DS])
        .agg(pl.col(Y).sum())
        for depth in range(1, len(hierarchy))
    ]

    return (
        pl.concat(levels).select(PARENT_LEVEL, SERIES_ID, DS, Y).sort([PARENT_LEVEL, SERIES_ID, DS])
    )
