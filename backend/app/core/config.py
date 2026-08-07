from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "Forecasting Platform"
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

    # Supabase is the platform's store of record. `database_url` is what it
    # falls back to when Supabase is not configured or cannot be reached.
    supabase_db_url: str = ""
    supabase_url: str = ""
    supabase_db_password: str = ""
    supabase_db_user: str = "postgres"
    supabase_db_name: str = "postgres"
    supabase_db_port: int = 5432

    database_url: str = "postgresql+asyncpg://forecasting:forecasting@localhost:5432/forecasting"
    sync_database_url: str = (
        "postgresql+psycopg://forecasting:forecasting@localhost:5432/forecasting"
    )

    database_fallback_enabled: bool = True
    database_probe_timeout: float = 5.0

    storage_root: Path = Path("./storage")

    cors_origins_raw: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")

    credential_secret_key: str = "dev-only-insecure-key-change-me"

    max_upload_bytes: int = 20 * 1024 * 1024

    currency_symbol: str = "$"

    forecast_workers: int = 2

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
    interval_weight: float = 0.15
    sarimax_order_p: int = 1
    sarimax_order_d: int = 1
    sarimax_order_q: int = 1
    gbm_max_depth: int = 3
    gbm_learning_rate: float = 0.06

    default_horizon_daily: int = 30
    default_horizon_weekly: int = 13
    default_horizon_monthly: int = 6
    default_horizon_quarterly: int = 4

    scenario_confidence: float = 0.95

    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_max_tokens: int = 400
    llm_timeout_seconds: float = 10.0
    llm_temperature: float = 0.2
    llm_max_concurrent_rewrites: int = 8

    anthropic_api_key: str | None = None
    insight_llm_model: str = "claude-3-5-sonnet-20241022"

    insight_accuracy_warning: float = 80.0
    insight_accuracy_plannable: float = 75.0
    insight_anomaly_z_threshold: float = 2.5
    insight_downside_severe_pct: float = 15.0

    divergence_sigmas: float = 12.0
    tuning_max_evaluations: int = 24
    tuning_min_validation_rows: int = 6
    ensemble_max_members: int = 4
    ensemble_min_improvement: float = 0.02

    min_gbm_rows: int = 8
    observations_per_parameter: int = 3
    max_state_space_period: int = 24

    series_fan_out_chunk: int = 10
    usage_events_limit: int = 5000

    api_max_page_size: int = 200

    @property
    def supabase_project_ref(self) -> str:
        raw = self.supabase_url.strip()
        if not raw:
            return ""
        host = urlparse(raw if "://" in raw else f"https://{raw}").hostname or ""
        if not host.endswith(".supabase.co"):
            return ""
        return host.removesuffix(".supabase.co").removeprefix("db.")

    @property
    def supabase_dsn(self) -> str:
        """A plain ``postgresql://`` DSN for Supabase, or "" when unconfigured.

        Either give the whole connection string Supabase shows under Project
        Settings → Database, or give the project URL and the database password
        and let the host be derived from the project ref.
        """
        explicit = self.supabase_db_url.strip()
        if explicit:
            return explicit

        ref = self.supabase_project_ref
        if not ref or not self.supabase_db_password:
            return ""
        return (
            f"postgresql://{quote(self.supabase_db_user, safe='')}"
            f":{quote(self.supabase_db_password, safe='')}"
            f"@db.{ref}.supabase.co:{self.supabase_db_port}/{self.supabase_db_name}"
        )

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_dsn)

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.broker_url

    @property
    def distributed(self) -> bool:
        return bool(self.broker_url)

    @property
    def progress_channel_url(self) -> str:
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
