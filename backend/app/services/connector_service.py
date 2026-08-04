from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.connectors.base import TestOutcome
from app.connectors.registry import build_adapter, secret_keys
from app.core.errors import ConnectorError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import decrypt_credentials, encrypt_credentials
from app.database.base import utcnow
from app.models.entities import Connector, ConnectorCredential, Dataset
from app.models.enums import ConnectorStatus, ConnectorType
from app.schemas.connector import ConnectorRead, SchemaColumn, SchemaTable
from app.services import dataset_service

logger = get_logger(__name__)


async def list_connectors(session: AsyncSession) -> list[Connector]:
    result = await session.execute(
        select(Connector).options(selectinload(Connector.credential)).order_by(Connector.created_at)
    )
    return list(result.scalars().all())


async def get_connector(session: AsyncSession, connector_id: uuid.UUID) -> Connector:
    result = await session.execute(
        select(Connector)
        .options(selectinload(Connector.credential))
        .where(Connector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise NotFoundError(f"No connector with id {connector_id}.")
    return connector


def to_read_model(connector: Connector) -> ConnectorRead:
    from app.connectors.registry import get_adapter_class

    return ConnectorRead(
        id=connector.id,
        name=connector.name,
        type=connector.type,
        status=connector.status,
        config=connector.config or {},
        last_tested_at=connector.last_tested_at,
        last_error=connector.last_error,
        created_at=connector.created_at,
        updated_at=connector.updated_at,
        credential_keys=list(connector.credential.key_names) if connector.credential else [],
        supports_import=get_adapter_class(connector.type).supports_import,
    )


async def create_connector(
    session: AsyncSession,
    *,
    name: str,
    connector_type: ConnectorType,
    config: dict,
    credentials: dict[str, str],
) -> Connector:
    existing = await session.execute(select(Connector).where(Connector.name == name))
    if existing.scalar_one_or_none() is not None:
        raise ValidationError(f"A connector named '{name}' already exists.")

    connector = Connector(
        name=name,
        type=connector_type,
        status=ConnectorStatus.CONFIGURED
        if credentials or config
        else ConnectorStatus.NOT_CONFIGURED,
        config=_strip_secrets(connector_type, config),
    )
    session.add(connector)
    await session.flush()

    if credentials:
        await _store_credentials(session, connector, credentials)

    await session.flush()

    return await get_connector(session, connector.id)


async def update_connector(
    session: AsyncSession,
    connector_id: uuid.UUID,
    *,
    name: str | None = None,
    config: dict | None = None,
    credentials: dict[str, str] | None = None,
) -> Connector:
    connector = await get_connector(session, connector_id)

    if name:
        connector.name = name
    if config is not None:
        connector.config = _strip_secrets(connector.type, config)
    if credentials:
        await _store_credentials(session, connector, credentials)
        connector.status = ConnectorStatus.CONFIGURED

    await session.flush()
    return await get_connector(session, connector.id)


def _strip_secrets(connector_type: ConnectorType, config: dict) -> dict:
    secrets = secret_keys(connector_type)
    removed = secrets & set(config)
    if removed:
        logger.warning(
            "Dropped secret key(s) %s from connector config for type %s.",
            sorted(removed),
            connector_type.value,
        )
    return {k: v for k, v in config.items() if k not in secrets}


async def _store_credentials(
    session: AsyncSession, connector: Connector, credentials: dict[str, str]
) -> None:
    ciphertext, key_names = encrypt_credentials(credentials)

    result = await session.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_id == connector.id)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.encrypted_payload = ciphertext
        existing.key_names = key_names
    else:
        session.add(
            ConnectorCredential(
                connector_id=connector.id, encrypted_payload=ciphertext, key_names=key_names
            )
        )


def load_credentials(connector: Connector) -> dict[str, str]:
    if connector.credential is None:
        return {}
    return decrypt_credentials(connector.credential.encrypted_payload)


async def test_connector(
    session: AsyncSession,
    *,
    connector_id: uuid.UUID | None,
    connector_type: ConnectorType | None,
    config: dict,
    credentials: dict[str, str],
) -> TestOutcome:
    if connector_id is not None:
        connector = await get_connector(session, connector_id)
        resolved_type = connector.type
        resolved_config = {**(connector.config or {}), **config}

        resolved_credentials = {**load_credentials(connector), **credentials}
    else:
        if connector_type is None:
            raise ValidationError("Provide either connector_id or type to test a connection.")
        connector = None
        resolved_type = connector_type
        resolved_config = config
        resolved_credentials = credentials

    adapter = build_adapter(resolved_type, resolved_config, resolved_credentials)

    outcome = await asyncio.to_thread(adapter.test)

    if connector is not None:
        connector.status = outcome.status
        connector.last_tested_at = utcnow()
        connector.last_error = None if outcome.ok else outcome.message
        await session.flush()

    return outcome


async def list_schemas(session: AsyncSession, connector_id: uuid.UUID) -> list[SchemaTable]:
    connector = await get_connector(session, connector_id)
    adapter = build_adapter(connector.type, connector.config or {}, load_credentials(connector))

    if not adapter.supports_import:
        raise ConnectorError(
            f"{adapter.display_name} does not support schema discovery in this deployment."
        )

    tables = await asyncio.to_thread(adapter.list_tables)
    return [
        SchemaTable(
            schema_name=table.schema_name,
            table_name=table.table_name,
            row_estimate=table.row_estimate,
            columns=[
                SchemaColumn(name=name, data_type=data_type, nullable=nullable)
                for name, data_type, nullable in table.columns
            ],
        )
        for table in tables
    ]


async def import_dataset(
    session: AsyncSession,
    connector_id: uuid.UUID,
    *,
    schema: str | None,
    table: str | None,
    query: str | None,
    dataset_name: str | None,
    row_limit: int,
) -> Dataset:
    connector = await get_connector(session, connector_id)
    adapter = build_adapter(connector.type, connector.config or {}, load_credentials(connector))

    if not adapter.supports_import:
        raise ConnectorError(
            f"{adapter.display_name} is not configured for import in this deployment."
        )

    frame = await asyncio.to_thread(
        adapter.fetch, schema=schema, table=table, query=query, limit=row_limit
    )

    if frame.height == 0:
        raise ConnectorError("The import returned no rows.")

    name = dataset_name or table or f"{connector.name} import"
    dataset, _profile = await dataset_service.create_from_frame(
        session, frame, name=name, connector_id=connector.id, source_kind="connector"
    )

    connector.status = ConnectorStatus.CONNECTED
    connector.last_tested_at = utcnow()
    connector.last_error = None
    await session.flush()

    return dataset
