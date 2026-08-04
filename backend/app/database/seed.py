from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import func, select

from app.core.logging import configure_logging, get_logger
from app.database.sample_data import generate_csv_bytes
from app.database.session import session_scope
from app.models.entities import Connector, Dataset, ForecastRun
from app.models.enums import ConnectorStatus, ConnectorType, ForecastFrequency, RunStatus
from app.services import dataset_service, forecast_service

logger = get_logger(__name__)

SAMPLE_DATASET_NAME = "Sample Sales History"
SAMPLE_FILENAME = "sample_sales_history.csv"


SEED_CONNECTORS: tuple[tuple[str, ConnectorType, dict], ...] = (
    ("BigQuery", ConnectorType.BIGQUERY, {}),
    ("Snowflake", ConnectorType.SNOWFLAKE, {}),
    ("Amazon Redshift", ConnectorType.REDSHIFT, {"port": 5439}),
    ("SQL Server", ConnectorType.SQLSERVER, {"port": 1433}),
    ("MySQL", ConnectorType.MYSQL, {"port": 3306}),
    ("PostgreSQL", ConnectorType.POSTGRESQL, {"port": 5432}),
    ("Google Sheets", ConnectorType.GOOGLE_SHEETS, {}),
    ("Excel", ConnectorType.EXCEL, {}),
    ("REST API", ConnectorType.REST_API, {}),
    ("Salesforce", ConnectorType.SALESFORCE, {}),
)


async def seed_connectors() -> int:
    created = 0
    async with session_scope() as session:
        existing = {name for (name,) in (await session.execute(select(Connector.name))).all()}

        for name, connector_type, config in SEED_CONNECTORS:
            if name in existing:
                continue
            session.add(
                Connector(
                    name=name,
                    type=connector_type,
                    status=ConnectorStatus.NOT_CONFIGURED,
                    config=config,
                )
            )
            created += 1

    if created:
        logger.info("Seeded %d connector(s).", created)
    return created


async def seed_dataset() -> Dataset | None:
    async with session_scope() as session:
        existing = await session.execute(select(Dataset).where(Dataset.name == SAMPLE_DATASET_NAME))
        found = existing.scalar_one_or_none()
        if found is not None:
            logger.info("Sample dataset already present; skipping.")
            return found

        dataset, profile = await dataset_service.create_from_upload(
            session,
            generate_csv_bytes(),
            SAMPLE_FILENAME,
            name=SAMPLE_DATASET_NAME,
        )

        dataset = await dataset_service.configure(
            session,
            dataset.id,
            time_column="order_date",
            target_column="revenue",
            frequency=ForecastFrequency.MONTHLY,
            horizon=6,
        )

        logger.info(
            "Seeded sample dataset: %d rows, %d columns, %s..%s (%s)",
            dataset.row_count,
            dataset.column_count,
            dataset.date_range_start,
            dataset.date_range_end,
            profile.detected_frequency,
        )
        return dataset


async def seed_forecast(dataset_id: uuid.UUID) -> None:
    async with session_scope() as session:
        completed = await session.execute(
            select(func.count())
            .select_from(ForecastRun)
            .where(
                ForecastRun.dataset_id == dataset_id,
                ForecastRun.status == RunStatus.COMPLETED,
            )
        )
        if int(completed.scalar_one()) > 0:
            logger.info("A completed forecast already exists; skipping.")
            return

        run = await forecast_service.create_run(
            session,
            dataset_id=dataset_id,
            name="Sample Sales Forecast",
            region_column="region",
            category_column="product_category",
            weight_column="units_sold",
            frequency=ForecastFrequency.MONTHLY,
            horizon=6,
            confidence_level=0.8,
        )
        run_id = run.id

    logger.info("Running the seed forecast (this fits five candidate models)...")
    await forecast_service.execute_run(run_id)

    async with session_scope() as session:
        run = await forecast_service.get_run(session, run_id)
        if run.status is RunStatus.COMPLETED:
            logger.info(
                "Seed forecast complete: model=%s, accuracy=%s",
                run.selected_model.value if run.selected_model else "?",
                next(
                    (f"{m.value:.2f}%" for m in run.metrics if m.name == "accuracy"),
                    "n/a",
                ),
            )
        else:
            logger.warning(
                "Seed forecast finished with status %s: %s", run.status, run.error_message
            )


async def seed() -> None:
    configure_logging()
    await seed_connectors()
    dataset = await seed_dataset()
    if dataset is not None:
        await seed_forecast(dataset.id)


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
