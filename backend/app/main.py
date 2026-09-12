from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import current_user, permitted
from app.api.routes import (
    auth,
    connectors,
    dashboard,
    datasets,
    exports,
    forecasts,
    health,
    usage,
)
from app.core import broadcast, lifecycle
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    CompressExceptStreams,
    ConcurrencyLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeaders,
)
from app.database.session import active_target, engine
from app.schemas.common import ErrorResponse
from app.services.forecast_service import recover_interrupted_runs
from app.services.job_runner import executors
from app.services.mail_sender import sender as mail_sender
from app.services.progress_relay import relay
from app.services.retention_service import sweeper as retention_sweeper

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings.ensure_directories()

    executors.start()
    relay.start()
    broadcast.relay.start()
    retention_sweeper.start()
    mail_sender.start()
    interrupted = await recover_interrupted_runs()
    if interrupted:
        logger.warning(
            "Marked %d forecast run(s) interrupted by the previous process as retryable failures.",
            interrupted,
        )
    logger.info(
        "%s ready — storing to %s (%s), forecasts run %s.",
        settings.app_name,
        active_target.label,
        active_target.safe_url,
        "on Celery workers" if settings.distributed else "in this process",
    )
    if settings.metrics_need_a_token:
        logger.warning(
            "METRICS_ENABLED is on but METRICS_TOKEN is empty, so every scrape of "
            "/api/health/metrics is being refused. Set a token to collect them — the endpoint "
            "describes every route this deployment serves and is not served openly in production."
        )
    if settings.candidate_workers_shadowed:
        logger.warning(
            "FORECAST_CANDIDATE_WORKERS=%d is being ignored: FORECAST_MODEL_CONCURRENCY=%d is "
            "above 1, and candidates are backtested on threads whenever it is. Set "
            "FORECAST_MODEL_CONCURRENCY=1 to use processes instead, or leave it and drop "
            "FORECAST_CANDIDATE_WORKERS to 1 so the configuration says what is happening.",
            settings.forecast_candidate_workers,
            settings.forecast_model_concurrency,
        )
    if settings.rate_limit_enabled and not settings.rate_limit_trusted_proxies:
        logger.warning(
            "RATE_LIMIT_TRUSTED_PROXIES is empty, so X-Forwarded-For is ignored and every "
            "caller is counted by the address the socket reports. Behind a proxy that is the "
            "proxy, so all callers share one bucket; set it to the proxy's network to count "
            "them apart."
        )
    if "*" in settings.cors_origins:
        logger.warning(
            "CORS_ORIGINS is '*' while credentials are allowed, which no browser honours: it "
            "sends back the literal '*' and the browser drops every cross-origin answer. Name "
            "the frontend's origins instead."
        )
    if settings.supabase_configured and active_target.name != "supabase":
        logger.warning(
            "Supabase is configured but was unreachable at boot. This process is "
            "reading and writing the local fallback; restart it once Supabase is back."
        )

    yield

    lifecycle.begin_shutdown()
    stranded = await executors.drain(settings.shutdown_drain_seconds)
    if stranded:
        logger.warning(
            "%d forecast run(s) were still going after %.0fs and will be marked retryable.",
            stranded,
            settings.shutdown_drain_seconds,
        )

    await relay.stop()
    await broadcast.relay.stop()
    await retention_sweeper.stop()
    await mail_sender.stop()
    executors.shutdown()
    await engine.dispose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Forecasting Platform API",
    version=settings.app_version,
    description=(
        "Forecasting analytics API: connectors, dataset profiling, model selection, "
        "scenario forecasting and rule-derived insights."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    responses={
        400: {"model": ErrorResponse, "description": "The request could not be processed."},
        404: {"model": ErrorResponse, "description": "The resource does not exist."},
        422: {"model": ErrorResponse, "description": "The payload failed validation."},
        500: {"model": ErrorResponse, "description": "An unexpected server error."},
        503: {
            "model": ErrorResponse,
            "description": (
                "The server is at capacity, or a dependency this request needs is unavailable. "
                "Both carry Retry-After."
            ),
        },
    },
)

app.add_middleware(
    ConcurrencyLimitMiddleware,
    limit=settings.max_concurrent_requests,
    enabled=settings.load_shedding_enabled,
)
app.add_middleware(RateLimitMiddleware, enabled=settings.rate_limit_enabled)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(CompressExceptStreams)
app.add_middleware(SecurityHeaders)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "X-Request-ID",
        "Retry-After",
        "RateLimit-Limit",
        "RateLimit-Remaining",
        "RateLimit-Reset",
    ],
)

register_error_handlers(app)

api = APIRouter(prefix="/api")

api.include_router(health.router)

api.include_router(auth.router, dependencies=[Depends(current_user)])

guarded = [Depends(permitted)]
api.include_router(connectors.router, dependencies=guarded)
api.include_router(datasets.router, dependencies=guarded)
api.include_router(forecasts.router, dependencies=guarded)
api.include_router(dashboard.router, dependencies=guarded)
api.include_router(dashboard.insights_router, dependencies=guarded)
api.include_router(exports.router, dependencies=guarded)
api.include_router(usage.router, dependencies=guarded)

app.include_router(api)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/api/health",
    }
