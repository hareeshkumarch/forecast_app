from __future__ import annotations

from typing import Any

from app.connectors.base import ConnectorAdapter, FormField, TestOutcome
from app.connectors.sql import PostgresAdapter
from app.core.errors import ConnectorError
from app.models.enums import ConnectorStatus, ConnectorType


class UnavailableDriverAdapter(ConnectorAdapter):
    required_package: str = ""
    install_hint: str = ""

    def _driver_available(self) -> bool:
        import importlib.util

        try:
            return importlib.util.find_spec(self.required_package) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def test(self) -> TestOutcome:
        missing = self._missing_required()
        if missing:
            return self._not_configured()

        if not self._driver_available():
            return TestOutcome(
                ok=False,
                status=ConnectorStatus.NOT_CONFIGURED,
                message=(
                    f"Credentials are saved, but the {self.display_name} driver "
                    f"('{self.required_package}') is not installed in this deployment. "
                    f"{self.install_hint}"
                ),
            )

        return TestOutcome(
            ok=False,
            status=ConnectorStatus.NOT_CONFIGURED,
            message=(
                f"The {self.display_name} driver is present but this POC does not "
                "ship a validated integration for it yet."
            ),
        )


class BigQueryAdapter(UnavailableDriverAdapter):
    type = ConnectorType.BIGQUERY
    display_name = "BigQuery"
    required_package = "google.cloud.bigquery"
    install_hint = "Add 'google-cloud-bigquery' to backend/requirements.txt to enable it."
    form_fields = (
        FormField("project_id", "GCP project ID", placeholder="my-analytics-project"),
        FormField("database", "Dataset", placeholder="sales"),
        FormField(
            "service_account_json",
            "Service account JSON",
            secret=True,
            kind="textarea",
            help_text="Paste the full service-account key file contents.",
        ),
    )


class SnowflakeAdapter(UnavailableDriverAdapter):
    type = ConnectorType.SNOWFLAKE
    display_name = "Snowflake"
    required_package = "snowflake.connector"
    install_hint = "Add 'snowflake-connector-python' to backend/requirements.txt to enable it."
    form_fields = (
        FormField("account", "Account identifier", placeholder="xy12345.eu-west-1"),
        FormField("warehouse", "Warehouse", placeholder="COMPUTE_WH"),
        FormField("database", "Database", placeholder="ANALYTICS"),
        FormField("schema_name", "Schema", required=False, placeholder="PUBLIC"),
        FormField("username", "Username", secret=True),
        FormField("password", "Password", secret=True, kind="password"),
    )


class GoogleSheetsAdapter(UnavailableDriverAdapter):
    type = ConnectorType.GOOGLE_SHEETS
    display_name = "Google Sheets"
    required_package = "googleapiclient"
    install_hint = "Add 'google-api-python-client' to backend/requirements.txt to enable it."
    form_fields = (
        FormField(
            "sheet_id",
            "Spreadsheet ID",
            placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
            help_text="The long identifier in the sheet's URL.",
        ),
        FormField("schema_name", "Worksheet name", required=False, placeholder="Sheet1"),
        FormField(
            "service_account_json",
            "Service account JSON",
            secret=True,
            kind="textarea",
            help_text="Share the sheet with this service account's email address.",
        ),
    )


class SalesforceAdapter(UnavailableDriverAdapter):
    type = ConnectorType.SALESFORCE
    display_name = "Salesforce"
    required_package = "simple_salesforce"
    install_hint = "Add 'simple-salesforce' to backend/requirements.txt to enable it."
    form_fields = (
        FormField("endpoint", "Instance URL", placeholder="https://acme.my.salesforce.com"),
        FormField("username", "Username", secret=True),
        FormField("password", "Password", secret=True, kind="password"),
        FormField("token", "Security token", secret=True, kind="password"),
    )


class RedshiftAdapter(PostgresAdapter):
    type = ConnectorType.REDSHIFT
    display_name = "Amazon Redshift"
    default_port = 5439
    form_fields = (
        FormField(
            "host",
            "Cluster endpoint",
            placeholder="my-cluster.abc123.eu-west-1.redshift.amazonaws.com",
        ),
        FormField("port", "Port", required=False, kind="number", placeholder="5439"),
        FormField("database", "Database", placeholder="dev"),
        FormField("username", "Username", secret=True),
        FormField("password", "Password", secret=True, kind="password"),
    )


class SupabaseAdapter(PostgresAdapter):
    type = ConnectorType.SUPABASE
    display_name = "Supabase"
    default_port = 5432

    DIRECT_PORT = 5432
    POOLER_PORT = 6543

    form_fields = (
        FormField(
            "project_ref",
            "Project reference",
            placeholder="abcdefghijklmnopqrst",
            help_text="The subdomain in your project URL: https://<ref>.supabase.co",
        ),
        FormField("password", "Database password", secret=True, kind="password"),
        FormField(
            "host",
            "Host",
            required=False,
            placeholder="db.<ref>.supabase.co",
            help_text="Only needed for the pooler, e.g. aws-0-eu-west-1.pooler.supabase.com",
        ),
        FormField("port", "Port", required=False, kind="number", placeholder="5432"),
        FormField("database", "Database", required=False, placeholder="postgres"),
        FormField(
            "username",
            "Username",
            required=False,
            secret=True,
            placeholder="postgres",
            help_text="Leave blank unless you connect through the pooler.",
        ),
    )

    def _project_ref(self) -> str:
        return self._value("project_ref").strip()

    def _resolved_host(self) -> str:
        configured = self._value("host").strip()
        if configured:
            return configured

        ref = self._project_ref()
        if not ref:
            raise ConnectorError("A Supabase project reference or an explicit host is required.")
        return f"db.{ref}.supabase.co"

    def _resolved_username(self) -> str:
        configured = self._value("username").strip()
        if configured:
            return configured

        ref = self._project_ref()
        if self._port() == self.POOLER_PORT and ref:
            return f"postgres.{ref}"
        return "postgres"

    def _connect(self) -> Any:
        import psycopg2

        return psycopg2.connect(
            host=self._resolved_host(),
            port=self._port(),
            dbname=self._value("database").strip() or "postgres",
            user=self._resolved_username(),
            password=self._value("password"),
            connect_timeout=8,
            sslmode="require",
        )
