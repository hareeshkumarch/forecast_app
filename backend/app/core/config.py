from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "Forecasting Platform"
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

    database_url: str = "postgresql+asyncpg://forecasting:forecasting@localhost:5432/forecasting"
    sync_database_url: str = (
        "postgresql+psycopg://forecasting:forecasting@localhost:5432/forecasting"
    )

    storage_root: Path = Path("./storage")

    cors_origins_raw: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")

    credential_secret_key: str = "dev-only-insecure-key-change-me"

    max_upload_bytes: int = 20 * 1024 * 1024

    forecast_workers: int = 2

    # Set a broker to run forecasts on Celery. Left empty the platform stays
    # single-node and fits models in an in-process pool, which is what the
    # tests and a laptop want.
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    redis_url: str = ""
    forecast_task_soft_time_limit: int = 1_500
    forecast_task_time_limit: int = 1_800
    forecast_task_max_retries: int = 2

    forecast_max_folds: int = 5
    metric_weight_wmape: float = 0.50
    metric_weight_smape: float = 0.30
    metric_weight_rmse: float = 0.20
    sarimax_order_p: int = 1
    sarimax_order_d: int = 1
    sarimax_order_q: int = 1
    gbm_max_depth: int = 3
    gbm_learning_rate: float = 0.06

    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")

    anthropic_api_key: str | None = None
    insight_llm_model: str = "claude-3-5-sonnet-20241022"

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.broker_url

    @property
    def distributed(self) -> bool:
        """True when runs are dispatched to Celery rather than fitted in-process."""
        return bool(self.broker_url)

    @property
    def progress_channel_url(self) -> str:
        """Redis carries progress between the worker and whichever API serves the stream."""
        # A Celery broker can also be RabbitMQ. Passing an AMQP URL to
        # redis-py makes the relay reconnect forever, so only select a URL the
        # progress transport can actually use. The result backend is a useful
        # fallback for RabbitMQ-broker/Redis-backend deployments.
        for candidate in (self.redis_url, self.celery_result_backend, self.broker_url):
            if candidate.lower().startswith(("redis://", "rediss://", "unix://")):
                return candidate
        return ""

    @property
    def cors_origins(self) -> list[str]:
        cleaned = self.cors_origins_raw.strip().strip("[]")
        return [origin.strip().strip("\"'") for origin in cleaned.split(",") if origin.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.storage_root / "uploads"

    @property
    def parquet_dir(self) -> Path:
        return self.storage_root / "parquet"

    @property
    def exports_dir(self) -> Path:
        return self.storage_root / "exports"

    def ensure_directories(self) -> None:
        for directory in (self.uploads_dir, self.parquet_dir, self.exports_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
