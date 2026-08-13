from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import func, select, text

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.security import using_insecure_default_key
from app.database.base import utcnow
from app.database.session import active_target
from app.models.entities import ForecastRun
from app.models.enums import RunStatus

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    database: Annotated[str, Field(min_length=1)]
    database_target: Literal["supabase", "local"]
    database_host: Annotated[str, Field(min_length=1)]
    supabase_configured: bool
    storage_writable: bool
    forecast_workers: Annotated[int, Field(ge=0)]
    max_upload_mb: Annotated[float, Field(gt=0)]
    using_default_credential_key: bool
    environment: Literal["development", "test", "production"]
    database_fallback_enabled: bool
    queued_forecast_runs: Annotated[int, Field(ge=0)]
    running_forecast_runs: Annotated[int, Field(ge=0)]
    failed_forecast_runs: Annotated[int, Field(ge=0)]
    timestamp: Annotated[str, Field(min_length=1)]

    @computed_field
    @property
    def status(self) -> Literal["ok", "degraded"]:
        if self.database != "ok" or not self.storage_writable:
            return "degraded"
        # Serving from the fallback while Supabase is configured is working,
        # but not what the deployment asked for.
        if self.supabase_configured and self.database_target != "supabase":
            return "degraded"
        return "ok"


def _probe_storage() -> bool:
    try:
        settings.ensure_directories()
        probe = settings.exports_dir / ".health"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@router.get("/health", response_model=HealthResponse, summary="Service health")
async def health(session: SessionDep) -> HealthResponse:
    run_counts: dict[RunStatus, int] = {}
    try:
        await session.execute(text("SELECT 1"))
        database = "ok"
        run_counts_result = await session.execute(
            select(ForecastRun.status, func.count()).group_by(ForecastRun.status)
        )
        run_counts = {status: int(count) for status, count in run_counts_result}
    except Exception as exc:
        database = f"error: {type(exc).__name__}"

    storage_writable = await asyncio.to_thread(_probe_storage)

    return HealthResponse(
        database=database,
        database_target=active_target.name,
        database_host=active_target.safe_url,
        supabase_configured=settings.supabase_configured,
        storage_writable=storage_writable,
        forecast_workers=settings.forecast_workers,
        max_upload_mb=round(settings.max_upload_bytes / (1024 * 1024), 2),
        using_default_credential_key=using_insecure_default_key(),
        environment=settings.environment,
        database_fallback_enabled=settings.database_fallback_enabled,
        queued_forecast_runs=run_counts.get(RunStatus.PENDING, 0),
        running_forecast_runs=run_counts.get(RunStatus.RUNNING, 0),
        failed_forecast_runs=run_counts.get(RunStatus.FAILED, 0),
        timestamp=utcnow().isoformat(),
    )
