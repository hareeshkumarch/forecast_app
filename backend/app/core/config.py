from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "Forecasting Platform"
    environment: Literal["development", "test", "production"] = Field(
        default="development", alias="APP_ENV"
    )
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

    # ---- Off-box archival of uploads --------------------------------------
    #: A Supabase Storage bucket that finished uploads are copied into. Left
    #: empty the copy is skipped entirely and everything stays on local disk,
    #: which is the single-node default. This is a backup of the one artifact
    #: that cannot be regenerated, not a relocation of the read path — see
    #: app/core/object_store.py.
    storage_bucket: str = Field(default="", alias="SUPABASE_STORAGE_BUCKET")
    #: Needs insert rights on that bucket. The anon/publishable key can list a
    #: public bucket but generally cannot write, so this is usually a
    #: storage-scoped S3 access key or the service role key.
    storage_api_key: str = Field(default="", alias="SUPABASE_STORAGE_KEY")

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

    # ---- Model selection -------------------------------------------------
    # How many backtest folds a run gets, and how the metrics it measures are
    # weighed against each other when the winner is picked. The three metric
    # weights are relative, not required to sum to 1, but they cannot all be 0
    # or there would be nothing left to rank candidates on.
    forecast_max_folds: int = Field(default=5, ge=1, le=20)
    metric_weight_wmape: float = Field(default=0.50, ge=0.0, le=1.0)
    #: MASE, not sMAPE. sMAPE is undefined wherever an actual and its forecast
    #: are both zero, so on intermittent demand it scores only the weeks that
    #: happened to have sales and ranks candidates on that unrepresentative
    #: slice. MASE divides by the in-sample naive error, which is defined on
    #: series full of zeros and puts every series on one scale.
    metric_weight_mase: float = Field(default=0.30, ge=0.0, le=1.0)
    metric_weight_rmse: float = Field(default=0.20, ge=0.0, le=1.0)
    #: What a candidate's interval quality (Winkler) is worth beside its point error.
    interval_weight: float = Field(default=0.15, ge=0.0, le=1.0)

    # ---- Model hyperparameters -------------------------------------------
    sarimax_order_p: int = Field(default=1, ge=0, le=5)
    sarimax_order_d: int = Field(default=1, ge=0, le=2)
    sarimax_order_q: int = Field(default=1, ge=0, le=5)
    gbm_max_depth: int = Field(default=3, ge=1, le=10)
    gbm_learning_rate: float = Field(default=0.06, gt=0.0, le=1.0)
    #: Rows a design matrix needs after lag construction before GBM is worth trying.
    min_gbm_rows: int = Field(default=8, ge=2)

    # ---- Search and ensembling -------------------------------------------
    tuning_max_evaluations: int = Field(default=24, ge=1, le=500)
    tuning_min_validation_rows: int = Field(default=6, ge=2)
    ensemble_max_members: int = Field(default=4, ge=2, le=10)
    #: How much better than its best member a blend must be to be worth the complication.
    ensemble_min_improvement: float = Field(default=0.02, ge=0.0, lt=1.0)
    #: How far a backtest prediction may wander from the training level before it
    #: is called divergent and thrown away.
    divergence_sigmas: float = Field(default=12.0, gt=0.0)

    # ---- Forecast defaults -----------------------------------------------
    #: The horizon a dataset gets when nobody picks one, per detected frequency.
    default_horizon_daily: int = Field(default=30, ge=1, le=365)
    default_horizon_weekly: int = Field(default=13, ge=1, le=365)
    default_horizon_monthly: int = Field(default=6, ge=1, le=365)
    default_horizon_quarterly: int = Field(default=4, ge=1, le=365)
    #: The band the best/worst case quote, as distinct from the reported interval.
    scenario_confidence: float = Field(default=0.95, gt=0.0, lt=1.0)

    # ---- Calendar ----------------------------------------------------------
    #: The calendar month a fiscal year starts in. An ERP writing FY24-P01
    #: means the first period of its own year, not January — a US federal
    #: calendar starts in October, an Indian one in April, and reading P01 as
    #: January puts every period of that file three to nine months out.
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)

    # ---- LLM ---------------------------------------------------------------
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_max_tokens: int = Field(default=400, ge=1, le=8192)
    llm_timeout_seconds: float = Field(default=10.0, gt=0.0)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_max_concurrent_rewrites: int = Field(default=8, ge=1, le=64)

    anthropic_api_key: str | None = None
    insight_llm_model: str = "claude-3-5-sonnet-20241022"

    # ---- Insight thresholds ------------------------------------------------
    #: Below this backtested accuracy an insight warns the figures are directional.
    insight_accuracy_warning: float = Field(default=80.0, ge=0.0, le=100.0)
    #: Below this the recommendation stops treating the forecast as plannable.
    insight_accuracy_plannable: float = Field(default=75.0, ge=0.0, le=100.0)
    #: Standard deviations from fit before a period is called an anomaly.
    insight_anomaly_z_threshold: float = Field(default=2.5, gt=0.0)
    #: Downside percentage at which worst-case risk is raised to critical.
    insight_downside_severe_pct: float = Field(default=15.0, ge=0.0, le=100.0)

    # ---- Drift ------------------------------------------------------------
    #: Tracking signal (cumulative error over MAD) past which a scored run is
    #: called drifted — the classic Trigg limit is 4 mean absolute deviations.
    drift_tracking_signal_limit: float = Field(default=4.0, gt=0.0)
    #: Realized wMAPE past which a run is called drifted whatever its bias.
    drift_wmape_limit: float = Field(default=50.0, gt=0.0, le=100.0)

    # ---- API and fan-out ---------------------------------------------------
    #: Leaves dispatched per chunk when a grouped run is fanned out to workers.
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
        return self

    @property
    def metric_weights(self) -> dict[str, float]:
        """The scoring weights for a series that is not intermittent."""
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
