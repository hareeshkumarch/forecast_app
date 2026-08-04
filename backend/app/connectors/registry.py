from __future__ import annotations

from app.connectors.base import ConnectorAdapter, FormField
from app.connectors.cloud import (
    BigQueryAdapter,
    GoogleSheetsAdapter,
    RedshiftAdapter,
    SalesforceAdapter,
    SnowflakeAdapter,
    SupabaseAdapter,
)
from app.connectors.files import CsvAdapter, ExcelAdapter
from app.connectors.rest import RestApiAdapter
from app.connectors.sql import MySqlAdapter, PostgresAdapter, SqlServerAdapter
from app.core.errors import ConnectorError
from app.models.enums import ConnectorType

ADAPTERS: dict[ConnectorType, type[ConnectorAdapter]] = {
    ConnectorType.POSTGRESQL: PostgresAdapter,
    ConnectorType.MYSQL: MySqlAdapter,
    ConnectorType.SQLSERVER: SqlServerAdapter,
    ConnectorType.CSV: CsvAdapter,
    ConnectorType.EXCEL: ExcelAdapter,
    ConnectorType.REST_API: RestApiAdapter,
    ConnectorType.REDSHIFT: RedshiftAdapter,
    ConnectorType.BIGQUERY: BigQueryAdapter,
    ConnectorType.SNOWFLAKE: SnowflakeAdapter,
    ConnectorType.GOOGLE_SHEETS: GoogleSheetsAdapter,
    ConnectorType.SALESFORCE: SalesforceAdapter,
    ConnectorType.SUPABASE: SupabaseAdapter,
}


RAIL_ORDER: tuple[ConnectorType, ...] = (
    ConnectorType.BIGQUERY,
    ConnectorType.SNOWFLAKE,
    ConnectorType.REDSHIFT,
    ConnectorType.SQLSERVER,
    ConnectorType.MYSQL,
    ConnectorType.POSTGRESQL,
    ConnectorType.SUPABASE,
    ConnectorType.GOOGLE_SHEETS,
    ConnectorType.EXCEL,
    ConnectorType.REST_API,
    ConnectorType.SALESFORCE,
)


def get_adapter_class(connector_type: ConnectorType) -> type[ConnectorAdapter]:
    adapter = ADAPTERS.get(connector_type)
    if adapter is None:
        raise ConnectorError(f"No adapter is registered for connector type '{connector_type}'.")
    return adapter


def build_adapter(
    connector_type: ConnectorType,
    config: dict[str, object],
    credentials: dict[str, str],
) -> ConnectorAdapter:
    return get_adapter_class(connector_type)(config, credentials)


def form_fields(connector_type: ConnectorType) -> tuple[FormField, ...]:
    return get_adapter_class(connector_type).form_fields


def secret_keys(connector_type: ConnectorType) -> set[str]:
    return {field.key for field in form_fields(connector_type) if field.secret}


def split_submission(
    connector_type: ConnectorType, values: dict[str, object]
) -> tuple[dict[str, object], dict[str, str]]:
    secrets = secret_keys(connector_type)
    config: dict[str, object] = {}
    credentials: dict[str, str] = {}

    for key, value in values.items():
        if value is None or value == "":
            continue
        if key in secrets:
            credentials[key] = str(value)
        else:
            config[key] = value

    return config, credentials


def describe(connector_type: ConnectorType) -> dict[str, object]:
    adapter = get_adapter_class(connector_type)
    return {
        "type": connector_type.value,
        "display_name": adapter.display_name,
        "supports_import": adapter.supports_import,
        "default_port": adapter.default_port,
        "fields": [
            {
                "key": field.key,
                "label": field.label,
                "secret": field.secret,
                "required": field.required,
                "kind": field.kind,
                "placeholder": field.placeholder,
                "help_text": field.help_text,
            }
            for field in adapter.form_fields
        ],
    }


def describe_all() -> list[dict[str, object]]:
    return [describe(connector_type) for connector_type in RAIL_ORDER]
