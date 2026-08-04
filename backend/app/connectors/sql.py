from __future__ import annotations

import time
from typing import Any

import polars as pl

from app.connectors.base import ConnectorAdapter, FormField, TableInfo, TestOutcome
from app.core.errors import ConnectorError
from app.core.logging import get_logger
from app.models.enums import ConnectorStatus, ConnectorType

logger = get_logger(__name__)


SYSTEM_SCHEMAS = {
    "information_schema",
    "pg_catalog",
    "pg_toast",
    "mysql",
    "performance_schema",
    "sys",
    "INFORMATION_SCHEMA",
}

_SQL_FORM = (
    FormField("host", "Host", placeholder="db.internal.example.com"),
    FormField("port", "Port", required=False, kind="number"),
    FormField("database", "Database", placeholder="analytics"),
    FormField("username", "Username", secret=True, placeholder="analytics_reader"),
    FormField("password", "Password", secret=True, kind="password"),
    FormField("ssl", "Require SSL", required=False, kind="checkbox"),
)


class SqlAdapter(ConnectorAdapter):

    supports_import = True
    form_fields = _SQL_FORM
    version_query = "SELECT version()"
    quote_char = '"'

    def _connect(self) -> Any:
        raise NotImplementedError

    def _quote(self, identifier: str) -> str:
        q = self.quote_char
        closing = {"[": "]"}.get(q, q)
        return f"{q}{identifier.replace(closing, closing * 2)}{closing}"


    def test(self) -> TestOutcome:
        if self._missing_required():
            return self._not_configured()

        started = time.perf_counter()
        try:
            connection = self._connect()
        except Exception as exc:
            return TestOutcome(
                ok=False,
                status=ConnectorStatus.ERROR,
                message=_friendly_error(exc, self.display_name),
                latency_ms=self._timed(started),
            )

        try:
            cursor = connection.cursor()
            cursor.execute(self.version_query)
            row = cursor.fetchone()
            version = str(row[0]) if row else None
            cursor.close()
        except Exception as exc:
            return TestOutcome(
                ok=False,
                status=ConnectorStatus.ERROR,
                message=f"Connected, but the version query failed: {exc}",
                latency_ms=self._timed(started),
            )
        finally:
            _close_quietly(connection)

        return TestOutcome(
            ok=True,
            status=ConnectorStatus.CONNECTED,
            message=f"Connected to {self.display_name} successfully.",
            latency_ms=self._timed(started),
            server_version=(version or "")[:200] or None,
        )

    def list_tables(self) -> list[TableInfo]:
        connection = self._open_or_raise()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT table_schema, table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                ORDER BY table_schema, table_name, ordinal_position
                """
            )
            rows = cursor.fetchall()
            cursor.close()
        except Exception as exc:
            raise ConnectorError(f"Could not list tables: {exc}") from exc
        finally:
            _close_quietly(connection)

        tables: dict[tuple[str, str], TableInfo] = {}
        for schema, table, column, data_type, nullable in rows:
            if schema in SYSTEM_SCHEMAS:
                continue
            key = (str(schema), str(table))
            info = tables.setdefault(key, TableInfo(schema_name=key[0], table_name=key[1]))
            info.columns.append((str(column), str(data_type), str(nullable).upper() == "YES"))

        return sorted(tables.values(), key=lambda t: (t.schema_name, t.table_name))

    def fetch(
        self, *, schema: str | None, table: str | None, query: str | None, limit: int
    ) -> pl.DataFrame:
        if not query and not table:
            raise ConnectorError("Provide either a table name or a SQL query to import.")

        if query:
            _reject_non_select(query)
            sql = f"SELECT * FROM ({query.rstrip(';')}) AS import_subquery {self._limit_clause(limit)}"
        else:
            qualified = (
                f"{self._quote(schema)}.{self._quote(table)}"  # type: ignore[arg-type]
                if schema
                else self._quote(table)  # type: ignore[arg-type]
            )
            sql = f"SELECT * FROM {qualified} {self._limit_clause(limit)}"

        connection = self._open_or_raise()
        try:
            cursor = connection.cursor()
            cursor.execute(sql)
            columns = [description[0] for description in cursor.description]
            rows = cursor.fetchall()
            cursor.close()
        except Exception as exc:
            raise ConnectorError(f"Import query failed: {exc}") from exc
        finally:
            _close_quietly(connection)

        if not rows:
            raise ConnectorError("The import query returned no rows.")

        return pl.DataFrame(
            [dict(zip(columns, row, strict=True)) for row in rows],
            infer_schema_length=None,
        )

    def _limit_clause(self, limit: int) -> str:
        return f"LIMIT {int(limit)}"

    def _open_or_raise(self) -> Any:
        try:
            return self._connect()
        except Exception as exc:
            raise ConnectorError(_friendly_error(exc, self.display_name)) from exc


class PostgresAdapter(SqlAdapter):
    type = ConnectorType.POSTGRESQL
    display_name = "PostgreSQL"
    default_port = 5432

    def _connect(self) -> Any:
        import psycopg2

        return psycopg2.connect(
            host=str(self.config.get("host")),
            port=int(self.config.get("port") or self.default_port),
            dbname=str(self.config.get("database") or "postgres"),
            user=self.credentials.get("username"),
            password=self.credentials.get("password"),
            connect_timeout=8,
            sslmode="require" if self.config.get("ssl") else "prefer",
        )


class MySqlAdapter(SqlAdapter):
    type = ConnectorType.MYSQL
    display_name = "MySQL"
    default_port = 3306
    quote_char = "`"
    version_query = "SELECT VERSION()"

    def _connect(self) -> Any:
        import pymysql

        return pymysql.connect(
            host=str(self.config.get("host")),
            port=int(self.config.get("port") or self.default_port),
            database=str(self.config.get("database") or ""),
            user=self.credentials.get("username"),
            password=self.credentials.get("password", ""),
            connect_timeout=8,
            ssl={"ssl": {}} if self.config.get("ssl") else None,
        )


class SqlServerAdapter(SqlAdapter):
    type = ConnectorType.SQLSERVER
    display_name = "SQL Server"
    default_port = 1433
    quote_char = "["
    version_query = "SELECT @@VERSION"

    def _connect(self) -> Any:
        import pymssql

        return pymssql.connect(
            server=str(self.config.get("host")),
            port=str(self.config.get("port") or self.default_port),
            database=str(self.config.get("database") or ""),
            user=self.credentials.get("username"),
            password=self.credentials.get("password"),
            login_timeout=8,
            timeout=30,
        )

    def _limit_clause(self, limit: int) -> str:


        return f"ORDER BY (SELECT NULL) OFFSET 0 ROWS FETCH NEXT {int(limit)} ROWS ONLY"


def _reject_non_select(query: str) -> None:
    normalised = query.strip().rstrip(";").lstrip("(").lstrip()
    lowered = normalised.lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ConnectorError("Only SELECT (or WITH ... SELECT) queries can be imported.")

    if ";" in normalised:
        raise ConnectorError("Multiple statements are not allowed in an import query.")

    forbidden = (
        "insert ", "update ", "delete ", "drop ", "alter ", "create ",
        "truncate ", "grant ", "revoke ", "call ", "merge ",
    )
    padded = f" {lowered} "
    for keyword in forbidden:
        if f" {keyword}" in padded:
            raise ConnectorError(
                f"The query contains '{keyword.strip()}', which is not allowed on an import."
            )


def _friendly_error(exc: Exception, display_name: str) -> str:
    text = str(exc).strip() or type(exc).__name__
    lowered = text.lower()

    if "timed out" in lowered or "timeout" in lowered:
        return f"Timed out connecting to {display_name}. Check the host, port and firewall rules."
    if "authentication" in lowered or "password" in lowered or "access denied" in lowered:
        return f"{display_name} rejected the credentials. Check the username and password."
    if "could not translate host" in lowered or "unknown host" in lowered or "getaddrinfo" in lowered:
        return f"The host could not be resolved. Check the hostname for {display_name}."
    if "does not exist" in lowered and "database" in lowered:
        return "The specified database does not exist on that server."
    if "connection refused" in lowered:
        return f"Connection refused. Is {display_name} listening on that host and port?"

    return f"{display_name} connection failed: {text[:300]}"


def _close_quietly(connection: Any) -> None:
    try:
        connection.close()
    except Exception:
        logger.debug("Error closing connection", exc_info=True)
