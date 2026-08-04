
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import connectors, dashboard, datasets, exports, forecasts, health
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.database.session import engine
from app.services.job_runner import executors

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings.ensure_directories()
                                                                              
                                  
    executors.start()
    logger.info("%s ready.", settings.app_name)

    yield

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
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
                                                                      
    expose_headers=["Content-Disposition"],
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

app.include_router(api)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/api/health",
    }
