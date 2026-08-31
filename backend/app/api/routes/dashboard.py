from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DashboardQueryDep, SessionDep
from app.core.cache import dashboard_cache, forget_run, run_tag
from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.httpcache import (
    APP_REVISION,
    OPENAPI_RESPONSES,
    conditional,
    shape_token,
    version_token,
)
from app.schemas.dashboard import (
    BreakdownResponse,
    DashboardQuery,
    DashboardSummary,
    DecisionResponse,
    DriverResponse,
    InsightResponse,
    InsightRewriteRequest,
    InsightRewriteResponse,
    LlmCheckResponse,
    LlmCredentials,
)
from app.services import dashboard_service, forecast_service, insight_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

T = TypeVar("T", bound=BaseModel)


async def _read(
    request: Request,
    response: Response,
    session: AsyncSession,
    query: DashboardQuery,
    *,
    endpoint: str,
    model: type[BaseModel],
    compute: Callable[[], Awaitable[T]],
    extra: tuple[object, ...] = (),
) -> T | Response:
    """One dashboard read, answered as cheaply as it honestly can be.

    Three tiers, in order of what they cost:

    1. The browser already has this exact version — `304`, no aggregates, no
       body. One indexed run lookup and one insight high-water read is the
       whole cost of the request.
    2. This process computed it recently — the read-through cache answers, and
       a second tab opening the same dashboard waits on the first tab's
       computation instead of starting its own.
    3. Nobody has it — compute, store, stamp, return.

    The same token drives all three, which is the point. It is built from the
    run's own revision (`dashboard_service.revision`), the query that selected
    it, this endpoint's response *shape*, and the release. Nothing an answer
    depends on is outside it, so a cached entry cannot be stale — a change to
    any of those produces a different key and misses. Tags carry the run id so
    a deleted run's entries can be reclaimed at once rather than waiting out
    their TTL.

    A run that does not exist is not cached at all: the "no data yet" answer is
    cheap to build, and caching it would mean the first forecast a deployment
    ever runs appears to produce nothing until the entry expired.

    One invariant the types do not enforce: what is stored is the assembled
    response model, and every subsequent reader gets that same object.
    Serialising it does not mutate it, which is why this is safe — but a
    handler that reached in and changed a field would be changing it for
    everybody. Build a new model instead.
    """
    run = await forecast_service.resolve_run(session, query.run_id)
    token = version_token(
        endpoint,
        APP_REVISION,
        shape_token(model),
        query.view,
        query.start,
        query.end,
        *extra,
        *await dashboard_service.revision(session, run),
    )

    early = conditional(request, response, token)
    if early is not None:
        return early

    if run is None or not settings.dashboard_cache_enabled:
        return await compute()

    return await dashboard_cache.get_or_set(  # type: ignore[no-any-return]
        f"{endpoint}:{token}",
        compute,
        ttl_seconds=settings.dashboard_cache_ttl_seconds,
        tags=(run_tag(run.id),),
    )


@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="KPI cards",
    responses=OPENAPI_RESPONSES,
)
async def summary(
    request: Request,
    response: Response,
    session: SessionDep,
    query: DashboardQueryDep,
) -> DashboardSummary | Response:
    return await _read(
        request,
        response,
        session,
        query,
        endpoint="summary",
        model=DashboardSummary,
        compute=lambda: dashboard_service.summary(session, query),
    )


@router.get(
    "/breakdown",
    response_model=BreakdownResponse,
    summary="The forecast split by one of this run's own columns",
    responses=OPENAPI_RESPONSES,
)
async def breakdown(
    request: Request,
    response: Response,
    session: SessionDep,
    query: DashboardQueryDep,
    column: str = Query(
        min_length=1,
        max_length=200,
        description="A column from this run's grain, or its region or category slot.",
    ),
) -> BreakdownResponse | Response:
    return await _read(
        request,
        response,
        session,
        query,
        endpoint="breakdown",
        model=BreakdownResponse,
        compute=lambda: dashboard_service.breakdown(session, query, column),
        # The column is part of the answer, so it has to be part of the key.
        # Leaving it out would serve the region split to somebody who asked
        # for the category one, which is the classic way a cache goes wrong.
        extra=(column,),
    )


@router.get(
    "/decision",
    response_model=DecisionResponse,
    summary="What to commit to, what to be ready for, and what to do about it",
    responses=OPENAPI_RESPONSES,
)
async def decision(
    request: Request,
    response: Response,
    session: SessionDep,
    query: DashboardQueryDep,
) -> DecisionResponse | Response:
    return await _read(
        request,
        response,
        session,
        query,
        endpoint="decision",
        model=DecisionResponse,
        compute=lambda: dashboard_service.decision(session, query),
    )


@router.get(
    "/drivers",
    response_model=DriverResponse,
    summary="Top drivers",
    responses=OPENAPI_RESPONSES,
)
async def drivers(
    request: Request,
    response: Response,
    session: SessionDep,
    query: DashboardQueryDep,
) -> DriverResponse | Response:
    return await _read(
        request,
        response,
        session,
        query,
        endpoint="drivers",
        model=DriverResponse,
        compute=lambda: dashboard_service.drivers(session, query),
    )


insights_router = APIRouter(tags=["insights"])


@insights_router.get(
    "/insights",
    response_model=InsightResponse,
    summary="AI insights",
    responses=OPENAPI_RESPONSES,
)
async def insights(
    request: Request,
    response: Response,
    session: SessionDep,
    query: DashboardQueryDep,
) -> InsightResponse | Response:
    return await _read(
        request,
        response,
        session,
        query,
        endpoint="insights",
        model=InsightResponse,
        compute=lambda: dashboard_service.insights(session, query),
    )


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
    # The rewrite has changed what /insights answers, and the entries holding
    # the previous wording are already unreachable — their keys carry the old
    # insight high-water mark. Dropping them now returns the memory instead of
    # leaving it to the TTL.
    forget_run(run.id)
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
    forget_run(run.id)
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
