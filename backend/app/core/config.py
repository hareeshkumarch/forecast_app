from __future__ import annotations

from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secrets import hydrate


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "Forecasting Platform"
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    environment: Literal["development", "test", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

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

    storage_bucket: str = Field(default="", alias="STORAGE_BUCKET")
    storage_endpoint: str = Field(default="", alias="STORAGE_ENDPOINT")
    storage_access_key_id: str = Field(default="", alias="STORAGE_ACCESS_KEY_ID")
    storage_secret_access_key: str = Field(default="", alias="STORAGE_SECRET_ACCESS_KEY")
    storage_region: str = Field(default="ap-south-1", alias="STORAGE_REGION")

    cors_origins_raw: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")

    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    supabase_jwt_secret: str = Field(default="", alias="SUPABASE_JWT_SECRET")
    auth_allowed_email_domains_raw: str = Field(default="", alias="AUTH_ALLOWED_EMAIL_DOMAINS")
    auth_allowlist_raw: str = Field(default="", alias="AUTH_ALLOWLIST")
    auth_admin_emails_raw: str = Field(default="", alias="AUTH_ADMIN_EMAILS")
    auth_require_approval: bool = Field(default=True, alias="AUTH_REQUIRE_APPROVAL")

    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")
    smtp_starttls: bool = Field(default=True, alias="SMTP_STARTTLS")
    smtp_timeout_seconds: float = Field(default=15.0, gt=0.0)
    public_api_base_url: str = Field(default="", alias="PUBLIC_API_BASE_URL")

    db_statement_timeout_seconds: float = Field(
        default=30.0, ge=0.0, le=3600.0, alias="DB_STATEMENT_TIMEOUT_SECONDS"
    )
    db_write_timeout_seconds: float = Field(
        default=300.0, ge=0.0, le=7200.0, alias="DB_WRITE_TIMEOUT_SECONDS"
    )

    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_trusted_proxy_hops: int = Field(
        default=1, ge=1, le=8, alias="RATE_LIMIT_TRUSTED_PROXY_HOPS"
    )
    rate_limit_trusted_proxies_raw: str = Field(default="", alias="RATE_LIMIT_TRUSTED_PROXIES")

    max_concurrent_requests: int = Field(default=64, ge=1, le=4096, alias="MAX_CONCURRENT_REQUESTS")
    load_shedding_enabled: bool = Field(default=True, alias="LOAD_SHEDDING_ENABLED")

    sse_max_streams_per_client: int = Field(
        default=8, ge=1, le=256, alias="SSE_MAX_STREAMS_PER_CLIENT"
    )
    sse_max_streams_total: int = Field(default=256, ge=1, le=10_000, alias="SSE_MAX_STREAMS_TOTAL")
    sse_max_lifetime_seconds: float = Field(
        default=1_800.0, ge=30.0, le=86_400.0, alias="SSE_MAX_LIFETIME_SECONDS"
    )
    sse_retry_hint_ms: int = Field(default=5_000, ge=500, le=120_000, alias="SSE_RETRY_HINT_MS")
    sse_retry_after_seconds: int = Field(
        default=15, ge=1, le=3_600, alias="SSE_RETRY_AFTER_SECONDS"
    )

    shutdown_drain_seconds: float = Field(
        default=45.0, ge=0.0, le=1800.0, alias="SHUTDOWN_DRAIN_SECONDS"
    )

    retention_enabled: bool = Field(default=False, alias="RETENTION_ENABLED")
    retention_run_days: int = Field(default=90, ge=0, le=3650, alias="RETENTION_RUN_DAYS")
    retention_keep_runs: int = Field(default=20, ge=1, le=10_000, alias="RETENTION_KEEP_RUNS")
    retention_interval_seconds: float = Field(
        default=3_600.0, ge=60.0, le=86_400.0, alias="RETENTION_INTERVAL_SECONDS"
    )
    retention_batch: int = Field(default=10, ge=1, le=1_000, alias="RETENTION_BATCH")

    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    metrics_token: str = Field(default="", alias="METRICS_TOKEN")

    dashboard_cache_enabled: bool = Field(default=True, alias="DASHBOARD_CACHE_ENABLED")
    dashboard_cache_ttl_seconds: float = Field(
        default=300.0, gt=0.0, le=86_400.0, alias="DASHBOARD_CACHE_TTL_SECONDS"
    )
    dashboard_cache_max_entries: int = Field(
        default=600, ge=1, le=100_000, alias="DASHBOARD_CACHE_MAX_ENTRIES"
    )

    llm_breaker_failure_threshold: int = Field(
        default=4, ge=1, le=100, alias="LLM_BREAKER_FAILURE_THRESHOLD"
    )
    llm_breaker_reset_seconds: float = Field(
        default=30.0, gt=0.0, le=3600.0, alias="LLM_BREAKER_RESET_SECONDS"
    )

    credential_secret_key: str = "dev-only-insecure-key-change-me"

    max_upload_bytes: int = 20 * 1024 * 1024

    currency_symbol: str = "$"

    forecast_workers: int = 2
    forecast_model_concurrency: int = Field(default=2, ge=1, le=8)
    forecast_blas_threads: int = Field(default=1, ge=1, le=64, alias="FORECAST_BLAS_THREADS")
    forecast_candidate_workers: int = Field(default=1, ge=1, le=8)

    celery_broker_url: str = ""
    celery_result_backend: str = ""
    redis_url: str = ""
    forecast_task_soft_time_limit: int = 1_500
    forecast_task_time_limit: int = 1_800
    forecast_task_max_retries: int = 2

    forecast_max_folds: int = Field(default=5, ge=1, le=20)
    metric_weight_wmape: float = Field(default=0.50, ge=0.0, le=1.0)
    metric_weight_mase: float = Field(default=0.30, ge=0.0, le=1.0)
    metric_weight_rmse: float = Field(default=0.20, ge=0.0, le=1.0)
    interval_weight: float = Field(default=0.15, ge=0.0, le=1.0)

    sarimax_order_p: int = Field(default=1, ge=0, le=5)
    sarimax_order_d: int = Field(default=1, ge=0, le=2)
    sarimax_order_q: int = Field(default=1, ge=0, le=5)
    gbm_max_depth: int = Field(default=3, ge=1, le=10)
    gbm_learning_rate: float = Field(default=0.06, gt=0.0, le=1.0)
    min_gbm_rows: int = Field(default=8, ge=2)

    tuning_max_evaluations: int = Field(default=24, ge=1, le=500)
    tuning_min_validation_rows: int = Field(default=6, ge=2)
    ensemble_max_members: int = Field(default=4, ge=2, le=10)
    ensemble_min_improvement: float = Field(default=0.02, ge=0.0, lt=1.0)
    divergence_sigmas: float = Field(default=12.0, gt=0.0)

    default_horizon_daily: int = Field(default=30, ge=1, le=365)
    default_horizon_weekly: int = Field(default=13, ge=1, le=365)
    default_horizon_monthly: int = Field(default=6, ge=1, le=365)
    default_horizon_quarterly: int = Field(default=4, ge=1, le=365)
    scenario_confidence: float = Field(default=0.95, gt=0.0, lt=1.0)

    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)

    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_max_tokens: int = Field(default=400, ge=1, le=8192)
    llm_timeout_seconds: float = Field(default=10.0, gt=0.0)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_max_concurrent_rewrites: int = Field(default=8, ge=1, le=64)

    anthropic_api_key: str | None = None
    insight_llm_model: str = "claude-opus-5"

    insight_accuracy_warning: float = Field(default=80.0, ge=0.0, le=100.0)
    insight_accuracy_plannable: float = Field(default=75.0, ge=0.0, le=100.0)
    insight_anomaly_z_threshold: float = Field(default=2.5, gt=0.0)
    insight_downside_severe_pct: float = Field(default=15.0, ge=0.0, le=100.0)

    drift_tracking_signal_limit: float = Field(default=4.0, gt=0.0)
    drift_wmape_limit: float = Field(default=50.0, gt=0.0, le=100.0)

    series_fan_out_chunk: int = Field(default=10, ge=1, le=1000)
    usage_events_limit: int = Field(default=5000, ge=1)
    api_max_page_size: int = Field(default=200, ge=1, le=1000)

    @model_validator(mode="after")
    def _metric_weights_rank_something(self) -> Settings:
        total = self.metric_weight_wmape + self.metric_weight_mase + self.metric_weight_rmse
        if total <= 0.0:
            raise ValueError(
                "METRIC_WEIGHT_WMAPE, METRIC_WEIGHT_MASE and METRIC_WEIGHT_RMSE cannot all be "
                "zero: model selection would have nothing left to rank candidates on."
            )
        if self.environment == "production":
            if self.database_fallback_enabled:
                raise ValueError(
                    "DATABASE_FALLBACK_ENABLED must be false in production so an unreachable "
                    "primary database cannot split writes onto a local node."
                )
            if (
                self.credential_secret_key == "dev-only-insecure-key-change-me"
                or len(self.credential_secret_key) < 32
            ):
                raise ValueError(
                    "CREDENTIAL_SECRET_KEY must be a non-default secret of at least 32 "
                    "characters in production."
                )
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS cannot contain '*' in production.")
            if secrets_load.configured and not secrets_load.loaded:
                raise ValueError(
                    "Infisical is configured but its secrets could not be read "
                    f"({secrets_load.error}). Refusing to start in production on partial "
                    "configuration — the defaults it would fall back to include sign-in "
                    "being switched off."
                )
            if not self.auth_enabled:
                raise ValueError(
                    "AUTH_ENABLED must be true in production. With it off every guarded route "
                    "resolves to the anonymous user and the whole API is served unauthenticated."
                )
        return self

    @property
    def metrics_need_a_token(self) -> bool:
        return self.metrics_enabled and self.environment == "production" and not self.metrics_token

    @property
    def metric_weights(self) -> dict[str, float]:
        return {
            "wmape": self.metric_weight_wmape,
            "mase": self.metric_weight_mase,
            "rmse": self.metric_weight_rmse,
        }

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
    def auth_allowed_email_domains(self) -> tuple[str, ...]:
        return tuple(
            part.strip().lower().lstrip("@")
            for part in self.auth_allowed_email_domains_raw.split(",")
            if part.strip()
        )

    @property
    def auth_admin_emails(self) -> tuple[str, ...]:
        return tuple(
            part.strip().lower() for part in self.auth_admin_emails_raw.split(",") if part.strip()
        )

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def auth_allowlist(self) -> tuple[str, ...]:
        return tuple(
            part.strip().lower() for part in self.auth_allowlist_raw.split(",") if part.strip()
        )

    @property
    def supabase_jwks_url(self) -> str:
        ref = self.supabase_project_ref
        return f"https://{ref}.supabase.co/auth/v1/.well-known/jwks.json" if ref else ""

    @property
    def supabase_issuer(self) -> str:
        ref = self.supabase_project_ref
        return f"https://{ref}.supabase.co/auth/v1" if ref else ""

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
    def candidate_workers_shadowed(self) -> bool:
        return self.forecast_candidate_workers > 1 and self.forecast_model_concurrency > 1

    @property
    def rate_limit_trusted_proxies(self) -> tuple[IPv4Network | IPv6Network, ...]:
        networks: list[IPv4Network | IPv6Network] = []
        for entry in self.rate_limit_trusted_proxies_raw.split(","):
            cleaned = entry.strip().strip("\"'")
            if not cleaned:
                continue
            try:
                networks.append(ip_network(cleaned, strict=False))
            except ValueError:
                continue
        return tuple(networks)

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


secrets_load = hydrate()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
