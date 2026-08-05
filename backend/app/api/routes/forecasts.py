from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import date

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.deps import SessionDep
from app.core.logging import get_logger
from app.database.session import session_scope
from app.datasets.profiler import is_currency_like
from app.forecasting.selection import SCORING_RULE
from app.models.entities import ModelCandidate
from app.models.enums import PointKind, RunStatus
from app.schemas.forecast import (
    ForecastMetricRead,
    ForecastMetricsResponse,
    ForecastPointRead,
    ForecastPointsResponse,
    ForecastRunDetail,
    ForecastRunRead,
    ForecastRunRequest,
    ModelCandidateRead,
    ScorecardResponse,
    ScoreRequest,
    SeriesResponse,
    SeriesRow,
    SeriesScoreRow,
)
from app.services import forecast_service, scoring_service, series_service
from app.services.job_runner import progress_bus

logger = get_logger(__name__)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


SSE_KEEPALIVE_SECONDS = 15.0

#: How many of a scorecard's series come back by default, and at most. The
#: scorecard itself is the headline; the list under it is a triage queue, and
#: a queue nobody reaches the end of is the same as a shorter one.
SCORE_SERIES_LIMIT = 25
MAX_SCORE_SERIES = series_service.MAX_PAGE


@router.get("", response_model=list[ForecastRunRead], summary="List forecast runs")
async def list_runs(session: SessionDep) -> list[ForecastRunRead]:
    runs = await forecast_service.list_runs(session)
    return [ForecastRunRead.model_validate(run) for run in runs]


@router.post(
    "/run",
    response_model=ForecastRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a forecast run",
)
async def start_run(payload: ForecastRunRequest, session: SessionDep) -> ForecastRunRead:
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
        metric_weights=payload.metric_weights,
        sarimax_order=payload.sarimax_order,
        gbm_max_depth=payload.gbm_max_depth,
        llm_provider=payload.llm_provider,
        llm_api_key=payload.llm_api_key,
        llm_model=payload.llm_model,
        llm_base_url=payload.llm_base_url,
        llm_input_cost_per_million=payload.llm_input_cost_per_million,
        llm_output_cost_per_million=payload.llm_output_cost_per_million,
    )

    await session.commit()
    await forecast_service.dispatch_run(session, run)

    return ForecastRunRead.model_validate(run)


@router.post(
    "/{run_id}/cancel",
    response_model=ForecastRunRead,
    summary="Cancel a queued or running forecast",
)
async def cancel_run(run_id: uuid.UUID, session: SessionDep) -> ForecastRunRead:
    run = await forecast_service.cancel_run(session, run_id)
    return ForecastRunRead.model_validate(run)


@router.get("/{run_id}", response_model=ForecastRunDetail, summary="Get a forecast run")
async def get_run(run_id: uuid.UUID, session: SessionDep) -> ForecastRunDetail:
    run = await forecast_service.get_run(session, run_id)
    return ForecastRunDetail.model_validate(run)


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
        scoring_rule=SCORING_RULE,
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


def _scorecard(
    card: scoring_service.Scorecard, target_column: str, limit: int
) -> ScorecardResponse:
    """
    Worst first, and bounded: a 500-series run would otherwise put its whole
    tree in a response nobody reads past the top of.
    """
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
        run = await forecast_service.get_run(session, run_id)
        initial = {
            "run_id": str(run.id),
            "status": run.status.value,
            "progress": run.progress,
            "stage": run.stage,
            "message": None,
            "selected_model": run.selected_model.value if run.selected_model else None,
            "error": run.error_message,
        }
        terminal = run.status in (RunStatus.COMPLETED, RunStatus.FAILED)

    async def event_source() -> AsyncIterator[bytes]:
        yield _sse(initial)
        if terminal:
            return

        subscription = progress_bus.subscribe(run_id).__aiter__()

        while True:
            try:
                event = await asyncio.wait_for(
                    subscription.__anext__(), timeout=SSE_KEEPALIVE_SECONDS
                )
            except TimeoutError:
                yield b": keep-alive\n\n"
                continue
            except StopAsyncIteration:
                break

            yield _sse(event.to_dict())
            if event.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                break

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


async def _latest_run_id(session: AsyncSession) -> uuid.UUID | None:
    run = await forecast_service.latest_completed_run(session)
    return run.id if run else None
