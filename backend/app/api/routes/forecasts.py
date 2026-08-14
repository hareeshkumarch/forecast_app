from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from typing import Annotated

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc  # noqa: UP017

from fastapi import APIRouter, Header, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.deps import SessionDep
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.database.session import session_scope
from app.datasets.profiler import is_currency_like
from app.forecasting.selection import scoring_rule
from app.models.entities import ForecastRun, ModelCandidate
from app.models.enums import PointKind, RunStatus
from app.schemas.forecast import (
    ForecastMetricRead,
    ForecastMetricsResponse,
    ForecastMonitoringResponse,
    ForecastPointRead,
    ForecastPointsResponse,
    ForecastProgressEvent,
    ForecastRunDetail,
    ForecastRunPage,
    ForecastRunRead,
    ForecastRunRequest,
    ModelCandidateRead,
    RunComparisonResponse,
    RunStateCounts,
    SavedScenarioCreate,
    SavedScenarioRead,
    ScorecardResponse,
    ScoreRequest,
    SeriesResponse,
    SeriesRow,
    SeriesScoreRow,
    WhatIfSimulationRequest,
    WhatIfSimulationResponse,
)
from app.services import (
    accuracy_service,
    forecast_service,
    scenario_service,
    scoring_service,
    series_service,
)
from app.services.job_runner import ProgressEvent, progress_bus
from app.services.progress_relay import latest_from_store

logger = get_logger(__name__)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


SSE_KEEPALIVE_SECONDS = 15.0

SCORE_SERIES_LIMIT = 25
MAX_SCORE_SERIES = series_service.MAX_PAGE


@router.get("", response_model=ForecastRunPage, summary="List forecast runs")
async def list_runs(
    session: SessionDep,
    search: str | None = Query(default=None, max_length=200),
    state: str | None = Query(
        default=None, description=f"One of: {', '.join(forecast_service.RUN_STATES)}."
    ),
    sort: str = Query(
        default=forecast_service.DEFAULT_RUN_SORT,
        description=f"One of: {', '.join(forecast_service.RUN_SORTS)}.",
    ),
    limit: int = Query(default=50, ge=1, le=forecast_service.MAX_RUN_PAGE),
    offset: int = Query(default=0, ge=0),
) -> ForecastRunPage:
    page = await forecast_service.list_runs(
        session, search=search, state=state, sort=sort, limit=limit, offset=offset
    )
    return ForecastRunPage(
        total=page.total,
        limit=limit,
        offset=offset,
        sort=sort if sort in forecast_service.RUN_SORTS else forecast_service.DEFAULT_RUN_SORT,
        counts=RunStateCounts(**page.counts),
        rows=[ForecastRunRead.model_validate(run) for run in page.rows],
    )


@router.post(
    "/run",
    response_model=ForecastRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a forecast run",
)
async def start_run(
    payload: ForecastRunRequest,
    session: SessionDep,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ] = None,
) -> ForecastRunRead:
    existing = await forecast_service.run_for_idempotency_key(session, idempotency_key)
    if existing is not None:
        return ForecastRunRead.model_validate(existing)

    run = await forecast_service.create_run(
        session,
        dataset_id=payload.dataset_id,
        name=payload.name,
        time_column=payload.time_column,
        target_column=payload.target_column,
        weight_column=payload.weight_column,
        region_column=payload.region_column,
        category_column=payload.category_column,
        group_by=payload.group_by,
        frequency=payload.frequency,
        horizon=payload.horizon,
        confidence_level=payload.confidence_level,
        aggregation=payload.aggregation,
        gap_fill=payload.gap_fill,
        outlier_treatment=payload.outlier_treatment,
        max_folds=payload.max_folds,
        max_series=payload.max_series,
        metric_weights=payload.metric_weights,
        sarimax_order=payload.sarimax_order,
        gbm_max_depth=payload.gbm_max_depth,
        gbm_learning_rate=payload.gbm_learning_rate,
        candidate_models=[m.value for m in payload.candidate_models]
        if payload.candidate_models
        else None,
        prophet_changepoint_prior_scale=payload.prophet_changepoint_prior_scale,
        prophet_interval_width=payload.prophet_interval_width,
        outlier_mad_threshold=payload.outlier_mad_threshold,
        complexity_penalty_scale=payload.complexity_penalty_scale,
        driver_columns=payload.driver_columns,
        llm_provider=payload.llm_provider,
        llm_api_key=payload.llm_api_key,
        llm_model=payload.llm_model,
        llm_base_url=payload.llm_base_url,
        llm_input_cost_per_million=payload.llm_input_cost_per_million,
        llm_output_cost_per_million=payload.llm_output_cost_per_million,
        idempotency_key=idempotency_key,
    )

    await session.commit()
    await forecast_service.dispatch_run(session, run)

    return ForecastRunRead.model_validate(run)


@router.get(
    "/compare",
    response_model=RunComparisonResponse,
    summary="Compare two issued forecast runs",
)
async def compare_runs(
    session: SessionDep,
    left_run_id: uuid.UUID = Query(),
    right_run_id: uuid.UUID = Query(),
) -> RunComparisonResponse:
    return await scenario_service.compare_runs(session, left_run_id, right_run_id)


@router.get(
    "/monitoring",
    response_model=ForecastMonitoringResponse,
    summary="Forecast health, drift and recovery queue",
)
async def monitor_runs(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> ForecastMonitoringResponse:
    return await scenario_service.monitoring(session, limit=limit)


@router.post(
    "/{run_id}/cancel",
    response_model=ForecastRunRead,
    summary="Cancel a queued or running forecast",
)
async def cancel_run(run_id: uuid.UUID, session: SessionDep) -> ForecastRunRead:
    run = await forecast_service.cancel_run(session, run_id)
    return ForecastRunRead.model_validate(run)


@router.post(
    "/{run_id}/retry",
    response_model=ForecastRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a failed forecast with the same configuration",
)
async def retry_run(
    run_id: uuid.UUID,
    session: SessionDep,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ] = None,
) -> ForecastRunRead:
    existing = await forecast_service.run_for_idempotency_key(session, idempotency_key)
    if existing is not None:
        return ForecastRunRead.model_validate(existing)
    run = await forecast_service.retry_run(session, run_id, idempotency_key=idempotency_key)
    await session.commit()
    await forecast_service.dispatch_run(session, run)
    return ForecastRunRead.model_validate(run)


@router.delete(
    "/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear a finished forecast run",
)
async def delete_run(run_id: uuid.UUID, session: SessionDep) -> Response:
    await forecast_service.delete_run(session, run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{run_id}", response_model=ForecastRunDetail, summary="Get a forecast run")
async def get_run(run_id: uuid.UUID, session: SessionDep) -> ForecastRunDetail:
    run = await forecast_service.get_run(session, run_id)
    detail = ForecastRunDetail.model_validate(run)
    current = await _current_progress(run)
    detail.status = current.status
    detail.progress = current.progress
    detail.stage = current.stage
    detail.error_message = current.error or detail.error_message
    detail.progress_updated_at = current.updated_at
    return detail


@router.get(
    "/accuracy/headline",
    summary="One accuracy figure across every scored run, with its evidence",
    description=(
        "What the accuracy section is entitled to claim, and on what basis. "
        "`publishable` is false until enough runs over enough periods have been scored."
    ),
)
async def get_headline_accuracy(session: SessionDep) -> dict:
    return (await accuracy_service.headline(session)).as_dict()


@router.get(
    "/{run_id}/accuracy",
    summary="How accurate this run turned out to be, and against what",
    description=(
        "WAPE and bias by horizon and series class, interval coverage, and value over "
        "baseline. Every figure carries the run and backtest configuration behind it, and "
        "`measured_against_outcomes` says whether it is scored against outcomes that have "
        "since arrived or against held-out stretches of your own history."
    ),
)
async def get_accuracy(run_id: uuid.UUID, session: SessionDep) -> dict:
    report = await accuracy_service.build(session, run_id)
    if report is None:
        raise NotFoundError(f"No forecast run with id {run_id}.")
    return report.as_dict()


@router.get(
    "/{run_id}/progress",
    response_model=ForecastProgressEvent,
    summary="Current recoverable forecast progress",
)
async def get_progress(run_id: uuid.UUID, session: SessionDep) -> dict:
    run = await forecast_service.get_run_state(session, run_id)
    return (await _current_progress(run)).to_dict()


@router.get(
    "/{run_id}/metrics",
    response_model=ForecastMetricsResponse,
    summary="Metrics and candidate scores",
)
async def get_metrics(run_id: uuid.UUID, session: SessionDep) -> ForecastMetricsResponse:
    run = await forecast_service.get_run(session, run_id)

    candidates = await session.execute(
        select(ModelCandidate).where(ModelCandidate.run_id == run.id).order_by(ModelCandidate.rank)
    )

    return ForecastMetricsResponse(
        run_id=run.id,
        selected_model=run.selected_model,
        selection_rationale=run.selection_rationale,
        leading_columns=list(run.leading_columns or []),
        frequency=run.frequency,
        scoring_rule=scoring_rule(),
        metrics=[ForecastMetricRead.model_validate(m) for m in run.metrics],
        candidates=[ModelCandidateRead.model_validate(c) for c in candidates.scalars().all()],
    )


@router.get(
    "/{run_id}/points", response_model=ForecastPointsResponse, summary="Forecast series points"
)
async def get_points(
    run_id: uuid.UUID,
    session: SessionDep,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    series_id: uuid.UUID | None = Query(
        default=None, description="Scope to one series of a grouped run; omit for the top line."
    ),
) -> ForecastPointsResponse:
    run = await forecast_service.get_run(session, run_id)
    points = await forecast_service.points_for_run(
        session, run_id, start=start, end=end, series_id=series_id
    )

    boundary = next(
        (index for index, point in enumerate(points) if point.kind is PointKind.FORECAST), None
    )

    return ForecastPointsResponse(
        run_id=run.id,
        frequency=run.frequency,
        confidence_level=run.confidence_level,
        boundary_index=boundary,
        points=[ForecastPointRead.model_validate(p) for p in points],
    )


@router.get(
    "/{run_id}/score",
    response_model=ScorecardResponse,
    summary="How this forecast did against what actually happened",
)
async def get_score(
    run_id: uuid.UUID,
    session: SessionDep,
    limit: int = Query(default=SCORE_SERIES_LIMIT, ge=0, le=MAX_SCORE_SERIES),
) -> ScorecardResponse:
    run = await forecast_service.get_run(session, run_id)
    card = await scoring_service.stored_scorecard(session, run_id)
    return _scorecard(card, run.target_column, limit)


@router.post(
    "/{run_id}/score",
    response_model=ScorecardResponse,
    summary="Score this forecast against actuals that have since arrived",
)
async def score(
    run_id: uuid.UUID,
    session: SessionDep,
    payload: ScoreRequest | None = None,
    limit: int = Query(default=SCORE_SERIES_LIMIT, ge=0, le=MAX_SCORE_SERIES),
) -> ScorecardResponse:
    run = await forecast_service.get_run(session, run_id)
    card = await scoring_service.score_run(
        session, run_id, dataset_id=payload.dataset_id if payload else None
    )
    await session.commit()
    return _scorecard(card, run.target_column, limit)


@router.post(
    "/{run_id}/simulate",
    response_model=WhatIfSimulationResponse,
    summary="Simulate what-if scenario shifts on a finished forecast",
)
async def simulate_run(
    run_id: uuid.UUID,
    payload: WhatIfSimulationRequest,
    session: SessionDep,
) -> WhatIfSimulationResponse:
    result = await forecast_service.simulate_what_if(
        session,
        run_id,
        volume_multiplier=payload.volume_multiplier,
        target_shift_pct=payload.target_shift_pct,
        driver_multipliers=payload.driver_multipliers,
    )
    return WhatIfSimulationResponse.model_validate(result)


@router.get(
    "/{run_id}/scenarios",
    response_model=list[SavedScenarioRead],
    summary="List saved scenarios for a forecast",
)
async def list_scenarios(run_id: uuid.UUID, session: SessionDep) -> list[SavedScenarioRead]:
    rows = await scenario_service.list_scenarios(session, run_id)
    return [SavedScenarioRead.model_validate(row) for row in rows]


@router.post(
    "/{run_id}/scenarios",
    response_model=SavedScenarioRead,
    status_code=status.HTTP_201_CREATED,
    summary="Simulate and save a named scenario",
)
async def save_scenario(
    run_id: uuid.UUID,
    payload: SavedScenarioCreate,
    session: SessionDep,
) -> SavedScenarioRead:
    scenario = await scenario_service.save_scenario(session, run_id, payload)
    await session.commit()
    return SavedScenarioRead.model_validate(scenario)


@router.delete(
    "/{run_id}/scenarios/{scenario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved scenario",
)
async def delete_scenario(
    run_id: uuid.UUID,
    scenario_id: uuid.UUID,
    session: SessionDep,
) -> Response:
    await scenario_service.delete_scenario(session, run_id, scenario_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _scorecard(
    card: scoring_service.Scorecard, target_column: str, limit: int
) -> ScorecardResponse:
    ranked = sorted(
        card.series,
        key=lambda row: (row.wmape is None, -(row.wmape or 0.0), row.label),
    )

    return ScorecardResponse(
        run_id=card.run_id,
        scored_at=card.scored_at,
        source_dataset_id=card.source_dataset_id,
        source_dataset_name=card.source_dataset_name,
        horizon=card.horizon,
        scored_periods=card.scored_periods,
        pending_periods=card.pending_periods,
        covered_through=card.covered_through,
        forecast_total=card.forecast_total,
        actual_total=card.actual_total,
        wmape=card.wmape,
        mae=card.mae,
        bias=card.bias,
        coverage=card.coverage,
        confidence_level=card.confidence_level,
        unforecast_keys=card.unforecast_keys,
        currency=is_currency_like(target_column),
        blocked_reason=card.blocked_reason,
        restated_since_scoring=card.restated_since_scoring,
        tracking_signal=card.tracking_signal,
        drifted=card.is_drifted,
        series=[SeriesScoreRow.model_validate(row, from_attributes=True) for row in ranked[:limit]],
    )


@router.get(
    "/{run_id}/series",
    response_model=SeriesResponse,
    summary="Series in a grouped run, worst first",
)
async def get_series(
    run_id: uuid.UUID,
    session: SessionDep,
    sort: str = Query(
        default=series_service.DEFAULT_SORT,
        description=f"One of: {', '.join(series_service.SORTS)}.",
    ),
    level: int | None = Query(default=None, ge=0, description="0 is the run's own total."),
    parent_id: uuid.UUID | None = Query(default=None, description="Only this series' children."),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=series_service.MAX_PAGE),
    offset: int = Query(default=0, ge=0),
) -> SeriesResponse:
    run = await forecast_service.get_run(session, run_id)

    rows, total = await series_service.list_series(
        session,
        run_id,
        sort=sort,
        level=level,
        parent_id=parent_id,
        search=search,
        limit=limit,
        offset=offset,
    )

    return SeriesResponse(
        run_id=run.id,
        group_by=list(run.group_by or []),
        sort=sort if sort in series_service.SORTS else series_service.DEFAULT_SORT,
        total=total,
        limit=limit,
        offset=offset,
        currency=is_currency_like(run.target_column),
        rows=[SeriesRow.model_validate(row) for row in rows],
    )


@router.get(
    "/{run_id}/events",
    summary="Server-Sent Events stream of forecast progress",
    response_class=StreamingResponse,
)
async def stream_events(run_id: uuid.UUID) -> StreamingResponse:
    async with session_scope() as session:
        run = await forecast_service.get_run_state(session, run_id)
        initial = await _current_progress(run)
        terminal = initial.status in (RunStatus.COMPLETED, RunStatus.FAILED)

    async def event_source() -> AsyncIterator[bytes]:
        yield _sse(initial.to_dict())
        if terminal:
            return

        progress_bus.publish(initial)
        subscription = progress_bus.subscribe(run_id)
        next_event: asyncio.Task[ProgressEvent] | None = asyncio.create_task(
            subscription.__anext__()
        )
        last_updated = _aware(initial.updated_at)

        try:
            while next_event is not None:
                ready, _ = await asyncio.wait((next_event,), timeout=SSE_KEEPALIVE_SECONDS)
                if not ready:
                    yield b": keep-alive\n\n"
                    continue

                try:
                    event = next_event.result()
                except StopAsyncIteration:
                    break

                if _aware(event.updated_at) > last_updated:
                    yield _sse(event.to_dict())
                    last_updated = _aware(event.updated_at)
                if event.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                    break
                next_event = asyncio.create_task(subscription.__anext__())
        finally:
            if next_event is not None and not next_event.done():
                next_event.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                    await next_event
            await subscription.aclose()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


async def _current_progress(run: ForecastRun) -> ProgressEvent:
    database = ProgressEvent(
        run_id=run.id,
        status=run.status,
        progress=run.progress,
        stage=run.stage,
        selected_model=run.selected_model.value if run.selected_model else None,
        error=run.error_message,
        updated_at=_aware(run.updated_at),
    )
    if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
        return database

    candidates = [database]
    in_process = progress_bus.latest(run.id)
    if in_process is not None:
        candidates.append(in_process)
    stored = await latest_from_store(run.id)
    if stored is not None:
        candidates.append(stored)
    terminal = [
        event for event in candidates if event.status in (RunStatus.COMPLETED, RunStatus.FAILED)
    ]
    if terminal:
        return max(terminal, key=lambda event: _aware(event.updated_at))
    return max(candidates, key=lambda event: (event.progress, _aware(event.updated_at)))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _latest_run_id(session: AsyncSession) -> uuid.UUID | None:
    run = await forecast_service.latest_completed_run(session)
    return run.id if run else None
