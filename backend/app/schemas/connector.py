from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ConnectorStatus, ConnectorType
from app.schemas.common import ORMModel


class ConnectorConfig(BaseModel):

    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = None
    schema_name: str | None = None
    warehouse: str | None = None
    project_id: str | None = None
    account: str | None = None
    endpoint: str | None = None
    sheet_id: str | None = None
    file_path: str | None = None
    ssl: bool = False
    options: dict[str, str] = Field(default_factory=dict)


class ConnectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: ConnectorType
    config: ConnectorConfig = Field(default_factory=ConnectorConfig)

    credentials: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Connector name cannot be blank.")
        return cleaned


class ConnectorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    config: ConnectorConfig | None = None
    credentials: dict[str, str] | None = None


class ConnectorTestRequest(BaseModel):

    connector_id: uuid.UUID | None = None
    type: ConnectorType | None = None
    config: ConnectorConfig = Field(default_factory=ConnectorConfig)
    credentials: dict[str, str] = Field(default_factory=dict)


class ConnectorTestResult(BaseModel):
    ok: bool
    status: ConnectorStatus
    message: str
    latency_ms: float | None = None
    server_version: str | None = None


class ConnectorRead(ORMModel):
    id: uuid.UUID
    name: str
    type: ConnectorType
    status: ConnectorStatus
    config: dict
    last_tested_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    credential_keys: list[str] = Field(default_factory=list)
    supports_import: bool = False


class SchemaColumn(BaseModel):
    name: str
    data_type: str
    nullable: bool = True


class SchemaTable(BaseModel):
    schema_name: str
    table_name: str
    row_estimate: int | None = None
    columns: list[SchemaColumn] = Field(default_factory=list)


class ConnectorSchemaList(BaseModel):
    connector_id: uuid.UUID
    tables: list[SchemaTable]


class ConnectorImportRequest(BaseModel):
    schema_name: str | None = None
    table_name: str | None = None

    query: str | None = None
    dataset_name: str | None = None
    row_limit: int = Field(default=500_000, ge=1, le=5_000_000)
