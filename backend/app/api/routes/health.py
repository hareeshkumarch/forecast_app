from __future__ import annotations

import asyncio
import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import func, select, text

from app.api.deps import SessionDep
from app.core import breaker, metrics
from app.core.auth import AuthError
from app.core.cache import CACHES
from app.core.config import secrets_load, settings
from app.core.errors import NotFoundError
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

    # This request is counted like any other, and worth saying why that is
    # harmless: the middleware measures it on the way out, after this body has
    # rendered, so a scrape never appears in its own output. It turns up in
    # the next one, which is what a scraper expects.
    return Response(content=metrics.registry.render(), media_type=PROMETHEUS_CONTENT_TYPE)
