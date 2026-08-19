from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import approved_user, current_user
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
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    CompressExceptStreams,
    RateLimitMiddleware,
    RequestContextMiddleware,
)
from app.database.session import active_target, engine
from app.schemas.common import ErrorResponse
from app.services.forecast_service import recover_interrupted_runs
from app.services.job_runner import executors
from app.services.progress_relay import relay

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings.ensure_directories()

    executors.start()
    relay.start()
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
    if settings.supabase_configured and active_target.name != "supabase":
        logger.warning(
            "Supabase is configured but was unreachable at boot. This process is "
            "reading and writing the local fallback; restart it once Supabase is back."
        )

    yield

    await relay.stop()
    executors.shutdown()
    await engine.dispose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Forecasting Platform API",
    version="0.1.0",
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
    },
)

# Order matters and reads backwards: add_middleware prepends, so the last one
# added is the outermost. RequestContextMiddleware therefore wraps the limiter,
# which is what lets a 429 carry a request id like every other answer. The
# limiter in turn wraps routing, so a request over its limit costs a dictionary
# lookup rather than a database round trip.
app.add_middleware(RateLimitMiddleware, enabled=settings.rate_limit_enabled)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(CompressExceptStreams)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)

register_error_handlers(app)

api = APIRouter(prefix="/api")

# Health stays open on purpose: the redeploy script polls it to decide whether
# what came back up is healthy, and a deployment that cannot answer that
# question cannot be deployed. It reports posture, never data.
api.include_router(health.router)

# Everything else is gated at the router, not per endpoint, so a route added
# later is protected by default rather than by whoever remembers to say so.
# Opened from an email, so it cannot require a session — a link that needs
# you to be signed in first is not one you can act on from your inbox. It
# carries a signature instead, which is what it is for.
api.include_router(auth.unauthenticated_router)

# The rest of the auth router takes the weaker gate on purpose: it has to be
# able to answer "you are waiting for approval", which a gate that requires
# approval could never say.
api.include_router(auth.router, dependencies=[Depends(current_user)])

guarded = [Depends(approved_user)]
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
