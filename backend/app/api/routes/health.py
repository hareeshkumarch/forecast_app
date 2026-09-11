from __future__ import annotations

import asyncio
import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, computed_field
from sqlalchemy import func, select, text

from app.api.deps import SessionDep
from app.core import breaker, lifecycle, metrics, streams
from app.core.auth import AuthError
from app.core.cache import CACHES
from app.core.config import secrets_load, settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.security import using_insecure_default_key
from app.database.base import utcnow
from app.database.session import active_target
from app.forecasting import availability
from app.forecasting.models import label_for
from app.models.entities import ForecastRun
from app.models.enums import ModelKind, RunStatus
from app.schemas.common import StrictModel
from app.services import capacity_service, retention_service
from app.services.job_runner import scheduler

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


class ModelCapabilityRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: ModelKind
    label: Annotated[str, Field(min_length=1)]
    available: bool
    reason: str | None = None


class CapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    models: tuple[ModelCapabilityRead, ...]

    @computed_field
    @property
    def unavailable_models(self) -> tuple[ModelKind, ...]:
        return tuple(row.model for row in self.models if not row.available)


class FeaturesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    series_status_filter: bool = True
    dataset_coverage: bool = True
    schema_mapping: bool = True
    access_approval: bool = True


class DependencyRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(min_length=1)]
    state: Literal["closed", "half_open", "open"]
    consecutive_failures: Annotated[int, Field(ge=0)]
    retry_after_seconds: Annotated[int, Field(ge=0)]


class CacheRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(min_length=1)]
    entries: Annotated[int, Field(ge=0)]
    hits: Annotated[int, Field(ge=0)]
    misses: Annotated[int, Field(ge=0)]
    coalesced: Annotated[int, Field(ge=0)]
    evictions: Annotated[int, Field(ge=0)]
    hit_ratio: Annotated[float, Field(ge=0.0, le=1.0)]


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
    unavailable_models: tuple[ModelKind, ...]
    auth_enabled: bool
    auth_requires_approval: bool
    secrets_source: str
    dependencies: tuple[DependencyRead, ...] = ()
    caches: tuple[CacheRead, ...] = ()
    open_streams: Annotated[int, Field(ge=0)] = 0
    max_streams: Annotated[int, Field(ge=1)] = 1
    timestamp: Annotated[str, Field(min_length=1)]

    @computed_field
    @property
    def status(self) -> Literal["ok", "degraded"]:
        if self.database != "ok" or not self.storage_writable:
            return "degraded"
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
    statuses = {
        row.model: row for row in await asyncio.to_thread(availability.optional_model_status)
    }

    return CapabilitiesResponse(
        models=tuple(
            ModelCapabilityRead(
                model=kind,
                label=label_for(kind),
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
    return await _capabilities()


class ReadyRead(StrictModel):
    ready: bool
    finishing: NonNegativeInt
    draining_seconds: float


@router.get(
    "/health/ready",
    response_model=ReadyRead,
    summary="Whether this instance should be sent traffic",
    description=(
        "Distinct from /api/health, which answers whether the process is alive. This answers "
        "whether it wants work — and goes false the moment a shutdown begins, so a load "
        "balancer takes the instance out while the forecasts already running are given time "
        "to land. Answering both questions with one endpoint meant a redeploy looked healthy "
        "while it was already tearing down."
    ),
    responses={503: {"description": "Draining. Do not send traffic here."}},
)
async def ready(response: Response) -> ReadyRead:
    draining = lifecycle.shutting_down()
    if draining:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        response.headers["Retry-After"] = "5"
    return ReadyRead(
        ready=not draining,
        finishing=scheduler.running if draining else 0,
        draining_seconds=round(lifecycle.draining_for(), 1),
    )


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
        auth_enabled=settings.auth_enabled,
        auth_requires_approval=settings.auth_enabled and settings.auth_require_approval,
        secrets_source="infisical" if secrets_load.loaded else "environment",
        dependencies=tuple(
            DependencyRead(
                name=snapshot.name,
                state=snapshot.state.value,
                consecutive_failures=snapshot.consecutive_failures,
                retry_after_seconds=snapshot.retry_after_seconds,
            )
            for snapshot in breaker.snapshots()
        ),
        caches=tuple(
            CacheRead(
                name=cache.name,
                entries=cache.stats.entries,
                hits=cache.stats.hits,
                misses=cache.stats.misses,
                coalesced=cache.stats.coalesced,
                evictions=cache.stats.evictions,
                hit_ratio=cache.stats.hit_ratio,
            )
            for cache in CACHES
        ),
        open_streams=streams.registry.total,
        max_streams=settings.sse_max_streams_total,
        timestamp=utcnow().isoformat(),
    )


@router.get(
    "/health/features",
    response_model=FeaturesResponse,
    summary="Which optional capabilities this deployment serves",
    description=(
        "A few bytes in place of the OpenAPI document, which the frontend was fetching once a "
        "session to learn the same thing. Public, like the rest of health: it reports posture, "
        "never data, and the frontend needs it before it knows whether anybody is signed in."
    ),
)
async def get_features() -> FeaturesResponse:
    return FeaturesResponse()


class TableUsageRead(StrictModel):
    name: str
    rows: NonNegativeInt
    bytes: NonNegativeInt | None


class StorageRead(StrictModel):
    total_bytes: NonNegativeInt | None
    total_rows: NonNegativeInt
    tables: tuple[TableUsageRead, ...]
    stored_runs: NonNegativeInt
    retention_enabled: bool
    retention_keep_runs: NonNegativeInt
    retention_older_than_days: NonNegativeInt
    prunable_runs: NonNegativeInt


@router.get(
    "/health/storage",
    response_model=StorageRead,
    summary="What this deployment has stored, and what could be pruned",
    include_in_schema=False,
)
async def storage(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
    fresh: bool = False,
) -> StorageRead:
    if not _scrape_permitted(authorization):
        raise AuthError("This endpoint needs the metrics token.")

    usage = await capacity_service.measure(session, fresh=fresh)
    intended = await retention_service.plan(session, limit=settings.retention_batch)

    return StorageRead(
        total_bytes=usage.total_bytes,
        total_rows=usage.total_rows,
        tables=tuple(
            TableUsageRead(name=table.name, rows=table.rows, bytes=table.bytes)
            for table in usage.tables
        ),
        stored_runs=await retention_service.stored_runs(session),
        retention_enabled=settings.retention_enabled,
        retention_keep_runs=settings.retention_keep_runs,
        retention_older_than_days=settings.retention_run_days,
        prunable_runs=intended.would_remove + intended.remaining,
    )


PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _scrape_permitted(authorization: str | None) -> bool:
    if not settings.metrics_token:
        return settings.environment != "production"

    presented = (authorization or "").strip()
    if not presented.lower().startswith("bearer "):
        return False
    return hmac.compare_digest(presented[7:].strip(), settings.metrics_token)


@router.get(
    "/health/metrics",
    summary="Counters, gauges and histograms for a Prometheus scrape",
    response_class=Response,
    responses={
        200: {
            "content": {"text/plain": {}},
            "description": "Prometheus text exposition format 0.0.4.",
        }
    },
    include_in_schema=False,
)
async def prometheus_metrics(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    if not settings.metrics_enabled:
        raise NotFoundError("This deployment does not serve metrics.")
    if not _scrape_permitted(authorization):
        raise AuthError("This scrape carried no valid metrics token.")

    await _refresh_storage_gauges(session)

    return Response(content=metrics.registry.render(), media_type=PROMETHEUS_CONTENT_TYPE)


async def _refresh_storage_gauges(session: SessionDep) -> None:
    try:
        usage = await capacity_service.measure(session)
    except Exception:
        logger.warning("Could not measure stored bytes for this scrape", exc_info=True)
        return

    for table in usage.tables:
        metrics.stored_rows.set(float(table.rows), table=table.name)
        if table.bytes is not None:
            metrics.stored_bytes.set(float(table.bytes), table=table.name)
