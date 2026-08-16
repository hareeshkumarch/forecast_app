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
from app.forecasting import availability
from app.forecasting.models import label_for
from app.models.entities import ForecastRun
from app.models.enums import ModelKind, RunStatus

router = APIRouter(tags=["health"])


class ModelCapabilityRead(BaseModel):
    """One model kind, and whether this deployment can fit it.

    Deliberately without the availability record's `operator_hint`. That field
    carries exception text and absolute paths from inside the container, and
    this response is served to any browser that can reach the distribution —
    the hint goes to the logs, where the person who can act on it is looking.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: ModelKind
    label: Annotated[str, Field(min_length=1)]
    available: bool
    #: Present only when `available` is false. Safe to render to a user.
    reason: str | None = None


class CapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    models: tuple[ModelCapabilityRead, ...]

    @computed_field
    @property
    def unavailable_models(self) -> tuple[ModelKind, ...]:
        return tuple(row.model for row in self.models if not row.available)


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
    #: Model kinds this deployment cannot fit — empty on a complete install.
    #: Here so that one `curl /api/health` answers "is Prophet live on this
    #: box?", which otherwise takes a shell on the instance to find out.
    unavailable_models: tuple[ModelKind, ...]
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


async def _capabilities() -> CapabilitiesResponse:
    # The probe shells out and imports Prophet, so it is slow exactly once per
    # process and instant after that. Off the event loop either way.
    statuses = {
        row.model: row for row in await asyncio.to_thread(availability.optional_model_status)
    }

    return CapabilitiesResponse(
        models=tuple(
            ModelCapabilityRead(
                model=kind,
                label=label_for(kind),
                # Anything the probe does not speak about is a model that is
                # always compiled in — statsmodels and scikit-learn are hard
                # requirements, so those kinds cannot be missing.
                available=statuses[kind.value].available if kind.value in statuses else True,
                reason=statuses[kind.value].reason if kind.value in statuses else None,
            )
            for kind in ModelKind
        )
    )


@router.get(
    "/health/capabilities",
    response_model=CapabilitiesResponse,
    summary="Which models this deployment can fit",
)
async def capabilities() -> CapabilitiesResponse:
    """The model roster, as this particular server can actually run it.

    The picker in the forecast dialog is built from this rather than from a
    list compiled into the frontend. A hardcoded roster offers Prophet on a
    deployment that has no Prophet, and the user finds out after waiting for
    a run that comes back with one dead candidate in it.
    """
    return await _capabilities()


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
        unavailable_models=(await _capabilities()).unavailable_models,
        timestamp=utcnow().isoformat(),
    )
