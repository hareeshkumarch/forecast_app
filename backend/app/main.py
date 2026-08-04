from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import connectors, dashboard, datasets, exports, forecasts, health, usage
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.database.session import engine
from app.schemas.common import ErrorResponse
from app.services.job_runner import executors
from app.services.progress_relay import relay

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings.ensure_directories()

    executors.start()
    relay.start()
    logger.info(
        "%s ready — forecasts run %s.",
        settings.app_name,
        "on Celery workers" if settings.distributed else "in this process",
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

app.add_middleware(RequestContextMiddleware)
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
api.include_router(health.router)
api.include_router(connectors.router)
api.include_router(datasets.router)
api.include_router(forecasts.router)
api.include_router(dashboard.router)
api.include_router(dashboard.insights_router)
api.include_router(exports.router)
api.include_router(usage.router)

app.include_router(api)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/api/health",
    }
