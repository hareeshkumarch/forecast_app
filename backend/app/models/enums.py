from enum import StrEnum


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
    SUPABASE = "supabase"
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


class SeriesStatus(StrEnum):
    FORECAST = "forecast"
    ESTIMATED = "estimated"
    POOLED = "pooled"
    BLOCKED = "blocked"


class AccessStatus(StrEnum):
    """Whether a signed-in account is allowed to use the platform.

    Signing in with Google proves who somebody is. It does not say they were
    meant to have an account here, so a new identity lands in PENDING and waits
    for a human to say otherwise.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AccessRole(StrEnum):
    """What a signed-in account may do.

    Held in the database rather than only in configuration, so an
    administrator can promote somebody without an environment change and a
    redeploy. The configured list stays authoritative as a floor — it is what
    stops a deployment being left with no administrator at all.
    """

    ADMIN = "admin"
    MEMBER = "member"
    #: Read the numbers, change nothing. Stored as a plain string like every
    #: other enum here, so adding it needed no migration — and nobody holds it
    #: until an administrator gives it to them, so nothing anybody can do today
    #: changes because it exists.
    VIEWER = "viewer"


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
    ETS = "ets"
    THETA = "theta"
    CROSTON = "croston"
    SARIMAX = "sarimax"
    PROPHET = "prophet"
    GRADIENT_BOOSTING = "gradient_boosting"
    ENSEMBLE = "ensemble"


class MeasureAggregation(StrEnum):
    SUM = "sum"
    MEAN = "mean"
    MEDIAN = "median"
    LAST = "last"
    MIN = "min"
    MAX = "max"


class GapFill(StrEnum):
    AUTO = "auto"
    INTERPOLATE = "interpolate"
    ZERO = "zero"
    NONE = "none"


class OutlierTreatment(StrEnum):
    NONE = "none"
    WINSORISE = "winsorise"


class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    SEVERE = "severe"


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
    PDF = "pdf"


class ExportStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
