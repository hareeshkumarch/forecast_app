from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import DashboardQueryDep, SessionDep
from app.core.errors import NotFoundError
from app.schemas.dashboard import (
    BreakdownResponse,
    DashboardQuery,
    DashboardSummary,
    DriverResponse,
    InsightResponse,
    InsightRewriteRequest,
    InsightRewriteResponse,
    LlmCheckResponse,
    LlmCredentials,
)
from app.services import dashboard_service, forecast_service, insight_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary, summary="KPI cards")
async def summary(session: SessionDep, query: DashboardQueryDep) -> DashboardSummary:
    return await dashboard_service.summary(session, query)


@router.get(
    "/breakdown",
    response_model=BreakdownResponse,
    summary="The forecast split by one of this run's own columns",
)
async def breakdown(
    session: SessionDep,
    query: DashboardQueryDep,
    column: str = Query(
        min_length=1,
        max_length=200,
        description="A column from this run's grain, or its region or category slot.",
    ),
) -> BreakdownResponse:
    return await dashboard_service.breakdown(session, query, column)


@router.get("/drivers", response_model=DriverResponse, summary="Top drivers")
async def drivers(session: SessionDep, query: DashboardQueryDep) -> DriverResponse:
    return await dashboard_service.drivers(session, query)


insights_router = APIRouter(tags=["insights"])


@insights_router.get("/insights", response_model=InsightResponse, summary="AI insights")
async def insights(session: SessionDep, query: DashboardQueryDep) -> InsightResponse:
    return await dashboard_service.insights(session, query)


@insights_router.post(
    "/insights/rewrite",
    response_model=InsightRewriteResponse,
    summary="Re-say this run's insights in the configured model's words",
)
async def rewrite_insights(
    session: SessionDep, payload: InsightRewriteRequest
) -> InsightRewriteResponse:
    run = await forecast_service.resolve_run(session, payload.run_id)
    if run is None:
        raise NotFoundError("There is no completed forecast to write insights for yet.")

    config = payload.model_dump(exclude={"run_id"})
    outcome = await insight_service.rewrite(session, run.id, config)
    stored = await dashboard_service.insights(session, _query_for(run.id))

    return InsightRewriteResponse(
        run_id=run.id,
        considered=outcome.considered,
        rewritten=outcome.rewritten,
        provider=outcome.provider,
        model=outcome.model,
        summary=outcome.summary,
        items=stored.items,
    )


@insights_router.post(
    "/insights/plain",
    response_model=InsightRewriteResponse,
    summary="Put the platform's own wording back",
)
async def plain_insights(session: SessionDep, query: DashboardQueryDep) -> InsightRewriteResponse:
    run = await forecast_service.resolve_run(session, query.run_id)
    if run is None:
        raise NotFoundError("There is no completed forecast to write insights for yet.")

    restored = await insight_service.reset(session, run.id)
    stored = await dashboard_service.insights(session, _query_for(run.id))

    return InsightRewriteResponse(
        run_id=run.id,
        considered=restored,
        rewritten=0,
        summary=f"{restored} insights are back to the platform's own wording.",
        items=stored.items,
    )


@insights_router.post(
    "/insights/check",
    response_model=LlmCheckResponse,
    summary="Ask the provider one question, to see whether the key works",
)
async def check_llm(payload: LlmCredentials) -> LlmCheckResponse:
    probe = await insight_service.check(payload.as_config())
    return LlmCheckResponse(
        ok=probe.ok,
        provider=probe.provider,
        model=probe.model,
        latency_ms=probe.latency_ms,
        message=probe.message,
        error_code=probe.error_code,
    )


def _query_for(run_id: uuid.UUID) -> DashboardQuery:
    return DashboardQuery(run_id=run_id)
