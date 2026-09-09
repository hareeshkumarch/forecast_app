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


class FeaturesResponse(BaseModel):
    """What this backend serves, in a few bytes.

    The frontend used to answer this by fetching /openapi.json — 158 KB and
    over a second on a phone, once per session, to learn two booleans. The
    document is still the fallback, because it is the only source that is true
    of a backend older than the frontend asking; this is the fast path for the
    usual case where they match.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    series_status_filter: bool = True
    dataset_coverage: bool = True
    schema_mapping: bool = True
    access_approval: bool = True


class DependencyRead(BaseModel):
    """One outbound dependency and whether calls to it are getting through."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(min_length=1)]
    state: Literal["closed", "half_open", "open"]
    consecutive_failures: Annotated[int, Field(ge=0)]
    #: Seconds until the breaker will let one trial call through. 0 when it is
    #: not open.
    retry_after_seconds: Annotated[int, Field(ge=0)]


class CacheRead(BaseModel):
    """One read-through cache, as it stands in this process."""

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
    #: Model kinds this deployment cannot fit — empty on a complete install.
    #: Here so that one `curl /api/health` answers "is Prophet live on this
    #: box?", which otherwise takes a shell on the instance to find out.
    unavailable_models: tuple[ModelKind, ...]
    #: Whether sign-in is being enforced, and where configuration came from.
    #: Posture, never data: it says a gate exists, not who is behind it.
    auth_enabled: bool
    auth_requires_approval: bool
    secrets_source: str
    #: Outbound dependencies, by the state of the breaker in front of each.
    #: Reported, never folded into `status` — see the property below.
    dependencies: tuple[DependencyRead, ...] = ()
    #: The read-through caches in this process. Operational, not diagnostic:
    #: a hit ratio that has collapsed is how you find out that something is
    #: writing to the runs on every request.
    caches: tuple[CacheRead, ...] = ()
    #: Live event-stream connections this process is holding, against its
    #: ceiling. Streams are exempt from the concurrency limit, so this is the
    #: only place the number shows up — and a figure sitting at the ceiling is
    #: how a deployment finds out its clients are reconnecting in a loop.
    open_streams: Annotated[int, Field(ge=0)] = 0
    max_streams: Annotated[int, Field(ge=1)] = 1
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
        # A tripped breaker is deliberately *not* degraded. This field is what
        # the load balancer reads, and the only dependency behind a breaker
        # today is the optional model provider that rewrites insight wording.
        # Pulling an instance out of service because an optional nicety is
        # unreachable would turn somebody else's outage into ours, at the
        # moment the remaining instances can least afford it. The state is
        # reported in `dependencies` for the person who wants to know.
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


class ReadyRead(StrictModel):
    """Should this process be sent traffic right now."""

    ready: bool
    #: Forecast runs still finishing while the process drains.
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
    # Every field defaults true. A deployment serving this endpoint at all is
    # new enough to have the features it describes — the version that lacked
    # them also lacks this route, which is what the fallback is for.
    return FeaturesResponse()


class TableUsageRead(StrictModel):
    name: str
    rows: NonNegativeInt
    bytes: NonNegativeInt | None


class StorageRead(StrictModel):
    """What has been stored, and what the retention policy would do about it.

    Behind the metrics token for the same reason the metrics are: row counts
    say how much a deployment has done, which is more than posture. The
    numbers are what any decision about retention has to start from — nothing
    in the platform used to delete anything, and the store of record has a
    ceiling.
    """

    total_bytes: NonNegativeInt | None
    total_rows: NonNegativeInt
    tables: tuple[TableUsageRead, ...]
    stored_runs: NonNegativeInt
    retention_enabled: bool
    retention_keep_runs: NonNegativeInt
    retention_older_than_days: NonNegativeInt
    #: Runs the next pass would remove, were retention on.
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


#: Prometheus' text exposition content type. The version parameter is part of
#: the contract, not decoration: a scraper uses it to decide how to parse.
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _scrape_permitted(authorization: str | None) -> bool:
    """Whether this scrape may read the metrics.

    A configured token is required whenever there is one. With none set, the
    answer depends on where this is running: open outside production, because
    the alternative is a developer needing a secret to look at their own
    counters and nothing on a laptop is worth protecting from the laptop —
    and refused in production, because an unset token there is a mistake, not
    a decision. The startup log says so when that happens; the endpoint does
    not quietly serve the route and error profile of a deployment on the
    internet while somebody gets round to it.

    `compare_digest` rather than `==` so the check does not leak the token one
    character at a time to somebody willing to measure.
    """
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
    """What this process has measured since it started.

    Not in the OpenAPI document, and not JSON: this is for a scraper, and the
    frontend has no use for it. Under `/api/health` so it inherits that
    prefix's exemption from rate limiting — a scrape every fifteen seconds
    would otherwise spend an allowance sized for a person clicking.

    404 rather than 403 when metrics are switched off. There is nothing here
    to be coy about, but an endpoint that answers "forbidden" has confirmed it
    exists, and a deployment that has turned this off has said it does not
    want to be asked.
    """
    if not settings.metrics_enabled:
        raise NotFoundError("This deployment does not serve metrics.")
    if not _scrape_permitted(authorization):
        raise AuthError("This scrape carried no valid metrics token.")

    await _refresh_storage_gauges(session)

    # This request is counted like any other, and worth saying why that is
    # harmless: the middleware measures it on the way out, after this body has
    # rendered, so a scrape never appears in its own output. It turns up in
    # the next one, which is what a scraper expects.
    return Response(content=metrics.registry.render(), media_type=PROMETHEUS_CONTENT_TYPE)


async def _refresh_storage_gauges(session: SessionDep) -> None:
    """Table sizes, read on scrape rather than kept up to date continuously.

    They only move when a run lands, and a counter maintained at write time is
    a second place for the number to be wrong. `measure` caches for a minute,
    so a scrape every fifteen seconds walks the catalogue once in four.

    Never allowed to fail the scrape. Everything else in this response is a
    process counter that cannot go wrong; this one asks the database, and a
    database having a bad moment must not also take away the metrics somebody
    is using to find out why.
    """
    try:
        usage = await capacity_service.measure(session)
    except Exception:
        logger.warning("Could not measure stored bytes for this scrape", exc_info=True)
        return

    for table in usage.tables:
        metrics.stored_rows.set(float(table.rows), table=table.name)
        if table.bytes is not None:
            metrics.stored_bytes.set(float(table.bytes), table=table.name)
