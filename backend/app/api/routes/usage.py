from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.schemas.usage import LlmUsageResponse
from app.services import usage_service

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/llm", response_model=LlmUsageResponse, summary="LLM request and token usage")
async def llm_usage(
    session: SessionDep,
    days: int = Query(default=30, ge=1, le=365),
) -> LlmUsageResponse:
    return await usage_service.summary(session, days=days)
