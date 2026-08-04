from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class ConnectorType(StrEnum):
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQLSERVER = "sqlserver"
    CSV = "csv"
    EXCEL = "excel"
    REST_API = "rest_api"
    BIGQUERY = "bigquery"
    SNOWFLAKE = "snowflake"
    REDSHIFT = "redshift"
    GOOGLE_SHEETS = "google_sheets"
    SALESFORCE = "salesforce"


class ConnectorStatus(StrEnum):

    NOT_CONFIGURED = "not_configured"
    CONFIGURED = "configured"
    CONNECTED = "connected"
    ERROR = "error"


class DatasetStatus(StrEnum):
    UPLOADED = "uploaded"
    PROFILING = "profiling"
    READY = "ready"
    FAILED = "failed"


class ColumnRole(StrEnum):
    TIME = "time"
    TARGET = "target"
    DIMENSION = "dimension"
    MEASURE = "measure"
    WEIGHT = "weight"
    IGNORED = "ignored"


class ColumnKind(StrEnum):
    DATE = "date"
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"
    TEXT = "text"


class ForecastFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ModelKind(StrEnum):
    NAIVE = "naive"
    SEASONAL_NAIVE = "seasonal_naive"
    HOLT_WINTERS = "holt_winters"
    THETA = "theta"
    CROSTON = "croston"
    SARIMAX = "sarimax"
    GRADIENT_BOOSTING = "gradient_boosting"


class PointKind(StrEnum):
    ACTUAL = "actual"
    FITTED = "fitted"
    FORECAST = "forecast"


class InsightType(StrEnum):
    ACCURACY_CHANGE = "accuracy_change"
    FORECAST_GAP = "forecast_gap"
    REGIONAL_GROWTH = "regional_growth"
    CATEGORY_DECLINE = "category_decline"
    ANOMALY = "anomaly"
    CONFIDENCE_WIDENING = "confidence_widening"
    WORST_CASE_RISK = "worst_case_risk"
    DRIVER_POSITIVE = "driver_positive"
    DRIVER_NEGATIVE = "driver_negative"
    RECOMMENDATION = "recommendation"


class InsightSeverity(StrEnum):
    POSITIVE = "positive"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ExportFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"


class ExportStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
