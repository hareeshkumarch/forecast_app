from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import DashboardQueryDep, SessionDep
from app.schemas.dashboard import (
    BreakdownResponse,
    CategoryResponse,
    DashboardSummary,
    DriverResponse,
    InsightResponse,
    RegionResponse,
)
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary, summary="KPI cards")
async def summary(session: SessionDep, query: DashboardQueryDep) -> DashboardSummary:
    return await dashboard_service.summary(session, query)


@router.get("/regions", response_model=RegionResponse, summary="Forecast by region")
async def regions(session: SessionDep, query: DashboardQueryDep) -> RegionResponse:
    return await dashboard_service.regions(session, query)


@router.get("/categories", response_model=CategoryResponse, summary="Forecast by category")
async def categories(session: SessionDep, query: DashboardQueryDep) -> CategoryResponse:
    return await dashboard_service.categories(session, query)


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
