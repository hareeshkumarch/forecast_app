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
)
from app.services import forecast_service
from app.services.job_runner import progress_bus

logger = get_logger(__name__)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


SSE_KEEPALIVE_SECONDS = 15.0


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
    )

    await session.commit()

    task = asyncio.create_task(forecast_service.execute_run(run.id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return ForecastRunRead.model_validate(run)


_background_tasks: set[asyncio.Task] = set()


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
) -> ForecastPointsResponse:
    run = await forecast_service.get_run(session, run_id)
    points = await forecast_service.points_for_run(session, run_id, start=start, end=end)

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
