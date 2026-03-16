import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import health, upload, forecast, jobs, websocket, demos
from app.core.websocket_manager import manager
from app.core.logging import logger
from app.database.session import engine, Base

from sqlalchemy import text

async def init_db():
    async with engine.begin() as conn:
        # Create tables if they don't exist
        await conn.run_sync(Base.metadata.create_all)
        
        # Simple migration for existing SQLite database
        if settings.DATABASE_URL.startswith("sqlite"):
            try:
                res = await conn.execute(text("PRAGMA table_info(jobs)"))
                columns = [row[1] for row in res.all()]
                
                migrations = [
                    ("user_id", "TEXT DEFAULT 'anonymous'"),
                    ("name", "TEXT DEFAULT 'Forecast Job'"),
                    ("original_filename", "TEXT"),
                    ("filename", "TEXT DEFAULT ''"),
                    ("date_col", "TEXT DEFAULT ''"),
                    ("target_col", "TEXT DEFAULT ''"),
                    ("exog_cols", "JSON DEFAULT '[]'"),
                    ("frequency", "TEXT DEFAULT 'auto'"),
                    ("horizon", "INTEGER DEFAULT 30"),
                    ("selected_models", "JSON DEFAULT '[]'"),
                    ("clean_anomalies", "BOOLEAN DEFAULT 0"),
                    ("hyperparameters", "JSON DEFAULT '{}'"),
                    ("preprocessing_report", "JSON DEFAULT '{}'"),
                    ("total_models", "INTEGER DEFAULT 0"),
                    ("completed_models", "INTEGER DEFAULT 0"),
                    ("error", "TEXT"),
                    ("created_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
                    ("updated_at", "DATETIME")
                ]
                
                for col_name, col_def in migrations:
                    if col_name not in columns:
                        logger.info(f"Migrating: Adding {col_name} to jobs table")
                        await conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def}"))

                res_mr = await conn.execute(text("PRAGMA table_info(model_results)"))
                mr_columns = [row[1] for row in res_mr.all()]
                if "tuning_metrics" not in mr_columns:
                    logger.info("Migrating: Adding tuning_metrics to model_results table")
                    await conn.execute(text("ALTER TABLE model_results ADD COLUMN tuning_metrics JSON"))

            except Exception as e:
                logger.error(f"Migration failed: {e}")

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs"
    )

    # Set all CORS enabled origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include Routers
    app.include_router(health.router, prefix=f"{settings.API_V1_STR}/health", tags=["health"])
    app.include_router(upload.router, prefix=f"{settings.API_V1_STR}/upload", tags=["dataset"])
    app.include_router(demos.router, prefix=f"{settings.API_V1_STR}/demos", tags=["dataset"])
    app.include_router(forecast.router, prefix=f"{settings.API_V1_STR}/forecast", tags=["ml"])
    app.include_router(jobs.router, prefix=f"{settings.API_V1_STR}/jobs", tags=["jobs"])
    app.include_router(websocket.router, tags=["websocket"])

    @app.on_event("startup")
    async def startup_event():
        logger.info("Initializing Database...")
        await init_db()
        logger.info("Starting Redis PubSub listener...")
        asyncio.create_task(manager.broadcast_from_redis())
        logger.info("ForecastHub ML Engine Started")

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
