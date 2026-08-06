from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import SessionDep
from app.connectors.registry import describe_all, split_submission
from app.schemas.connector import (
    ConnectorCreate,
    ConnectorImportRequest,
    ConnectorRead,
    ConnectorSchemaList,
    ConnectorTestRequest,
    ConnectorTestResult,
    ConnectorUpdate,
)
from app.schemas.dataset import DatasetRead
from app.services import connector_service

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("", response_model=list[ConnectorRead], summary="List connectors")
async def list_connectors(session: SessionDep) -> list[ConnectorRead]:
    connectors = await connector_service.list_connectors(session)
    return [connector_service.to_read_model(c) for c in connectors]


@router.get("/types", summary="Connector types and their form fields")
async def connector_types() -> list[dict]:
    return describe_all()


@router.post(
    "",
    response_model=ConnectorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a connector",
)
async def create_connector(payload: ConnectorCreate, session: SessionDep) -> ConnectorRead:
    submission: dict[str, object] = {
        **payload.config.model_dump(exclude_none=True),
        **payload.credentials,
    }
    config, credentials = split_submission(payload.type, submission)

    connector = await connector_service.create_connector(
        session,
        name=payload.name,
        connector_type=payload.type,
        config=config,
        credentials=credentials,
    )
    return connector_service.to_read_model(connector)


@router.post("/test", response_model=ConnectorTestResult, summary="Test a connection")
async def test_connection(
    payload: ConnectorTestRequest, session: SessionDep
) -> ConnectorTestResult:
    connector_type = payload.type
    submission: dict[str, object] = {
        **payload.config.model_dump(exclude_none=True),
        **payload.credentials,
    }

    if connector_type is not None:
        config, credentials = split_submission(connector_type, submission)
    else:
        config, credentials = submission, {}

    outcome = await connector_service.test_connector(
        session,
        connector_id=payload.connector_id,
        connector_type=connector_type,
        config=config,
        credentials={k: str(v) for k, v in credentials.items()},
    )

    return ConnectorTestResult(
        ok=outcome.ok,
        status=outcome.status,
        message=outcome.message,
        latency_ms=outcome.latency_ms,
        server_version=outcome.server_version,
    )


@router.get("/{connector_id}", response_model=ConnectorRead, summary="Get a connector")
async def get_connector(connector_id: uuid.UUID, session: SessionDep) -> ConnectorRead:
    connector = await connector_service.get_connector(session, connector_id)
    return connector_service.to_read_model(connector)


@router.patch("/{connector_id}", response_model=ConnectorRead, summary="Update a connector")
async def update_connector(
    connector_id: uuid.UUID, payload: ConnectorUpdate, session: SessionDep
) -> ConnectorRead:
    connector = await connector_service.get_connector(session, connector_id)

    config: dict | None = None
    credentials: dict[str, str] | None = None

    if payload.config is not None or payload.credentials is not None:
        submission: dict[str, object] = {
            **(payload.config.model_dump(exclude_none=True) if payload.config else {}),
            **(payload.credentials or {}),
        }
        split_config, split_credentials = split_submission(connector.type, submission)
        config = split_config if payload.config is not None else None
        credentials = split_credentials or None

    updated = await connector_service.update_connector(
        session, connector_id, name=payload.name, config=config, credentials=credentials
    )
    return connector_service.to_read_model(updated)


@router.delete(
    "/{connector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a connector",
)
async def delete_connector(connector_id: uuid.UUID, session: SessionDep) -> Response:
    await connector_service.delete_connector(session, connector_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{connector_id}/schemas",
    response_model=ConnectorSchemaList,
    summary="List tables and columns",
)
async def list_schemas(connector_id: uuid.UUID, session: SessionDep) -> ConnectorSchemaList:
    tables = await connector_service.list_schemas(session, connector_id)
    return ConnectorSchemaList(connector_id=connector_id, tables=tables)


@router.post(
    "/{connector_id}/import",
    response_model=DatasetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Import a table into a dataset",
)
async def import_table(
    connector_id: uuid.UUID, payload: ConnectorImportRequest, session: SessionDep
) -> DatasetRead:
    dataset = await connector_service.import_dataset(
        session,
        connector_id,
        schema=payload.schema_name,
        table=payload.table_name,
        query=payload.query,
        dataset_name=payload.dataset_name,
        row_limit=payload.row_limit,
    )
    return DatasetRead.model_validate(dataset)
