
from __future__ import annotations

import uuid
from datetime import date

import polars as pl
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.datasets.ingest import persist_upload, write_parquet
from app.datasets.profiler import DatasetProfileResult, profile_frame, suggestions
from app.models.entities import Dataset, DatasetColumn
from app.models.enums import ColumnRole, DatasetStatus, ForecastFrequency
from app.schemas.dataset import ColumnSuggestion, DatasetProfile

logger = get_logger(__name__)


async def list_datasets(session: AsyncSession, *, limit: int = 100) -> list[Dataset]:
    result = await session.execute(
        select(Dataset).order_by(Dataset.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> Dataset:
    result = await session.execute(
        select(Dataset).options(selectinload(Dataset.columns)).where(Dataset.id == dataset_id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise NotFoundError(f"No dataset with id {dataset_id}.")
    return dataset


async def create_from_upload(
    session: AsyncSession, content: bytes, filename: str, *, name: str | None = None
) -> tuple[Dataset, DatasetProfileResult]:
    dataset_id = uuid.uuid4()

    ingested = persist_upload(content, filename, str(dataset_id))
    profile = profile_frame(ingested.frame)
    parquet_path = write_parquet(ingested.frame, str(dataset_id))

    time_column = next((c.name for c in profile.columns if c.role is ColumnRole.TIME), None)
    target_column = next((c.name for c in profile.columns if c.role is ColumnRole.TARGET), None)

    dataset = Dataset(
        id=dataset_id,
        name=name or filename.rsplit(".", 1)[0][:200],
        original_filename=filename,
        source_kind="upload",
        status=DatasetStatus.READY,
        file_size_bytes=ingested.file_size_bytes,
        row_count=profile.row_count,
        column_count=profile.column_count,
        missing_value_count=profile.missing_value_count,
        parquet_path=str(parquet_path),
        raw_path=str(ingested.raw_path),
        date_range_start=profile.date_range_start,
        date_range_end=profile.date_range_end,
        time_column=time_column,
        target_column=target_column,
        frequency=profile.detected_frequency,
                                                                                 
        horizon=_default_horizon(profile.detected_frequency),
    )
    session.add(dataset)
    await session.flush()

    _attach_columns(session, dataset, profile)
    await session.flush()

                                                                            
    return await get_dataset(session, dataset.id), profile


async def create_from_frame(
    session: AsyncSession,
    frame: pl.DataFrame,
    *,
    name: str,
    connector_id: uuid.UUID | None = None,
    source_kind: str = "connector",
) -> tuple[Dataset, DatasetProfileResult]:
    dataset_id = uuid.uuid4()

    profile = profile_frame(frame)
    parquet_path = write_parquet(frame, str(dataset_id))

    time_column = next((c.name for c in profile.columns if c.role is ColumnRole.TIME), None)
    target_column = next((c.name for c in profile.columns if c.role is ColumnRole.TARGET), None)

    dataset = Dataset(
        id=dataset_id,
        name=name[:200],
        original_filename=None,
        source_kind=source_kind,
        connector_id=connector_id,
        status=DatasetStatus.READY,
        file_size_bytes=parquet_path.stat().st_size,
        row_count=profile.row_count,
        column_count=profile.column_count,
        missing_value_count=profile.missing_value_count,
        parquet_path=str(parquet_path),
        date_range_start=profile.date_range_start,
        date_range_end=profile.date_range_end,
        time_column=time_column,
        target_column=target_column,
        frequency=profile.detected_frequency,
        horizon=_default_horizon(profile.detected_frequency),
    )
    session.add(dataset)
    await session.flush()

    _attach_columns(session, dataset, profile)
    await session.flush()

    return await get_dataset(session, dataset.id), profile


def _default_horizon(frequency: ForecastFrequency | None) -> int:
    return {
        ForecastFrequency.DAILY: 30,
        ForecastFrequency.WEEKLY: 13,
        ForecastFrequency.MONTHLY: 6,
        ForecastFrequency.QUARTERLY: 4,
    }.get(frequency or ForecastFrequency.MONTHLY, 6)


def _attach_columns(
    session: AsyncSession, dataset: Dataset, profile: DatasetProfileResult
) -> None:
    for column in profile.columns:
        session.add(
            DatasetColumn(
                dataset_id=dataset.id,
                name=column.name,
                position=column.position,
                kind=column.kind,
                role=column.role,
                dtype=column.dtype,
                null_count=column.null_count,
                distinct_count=column.distinct_count,
                min_value=column.min_value,
                max_value=column.max_value,
                mean_value=column.mean_value,
                sample_values=column.sample_values,
                is_date_candidate=column.is_date_candidate,
                is_target_candidate=column.is_target_candidate,
            )
        )


async def configure(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    time_column: str,
    target_column: str,
    frequency: ForecastFrequency,
    horizon: int,
    name: str | None = None,
) -> Dataset:
    dataset = await get_dataset(session, dataset_id)
    available = {column.name for column in dataset.columns}

    for label, value in (("time", time_column), ("target", target_column)):
        if value not in available:
            raise ValidationError(
                f"'{value}' is not a column in this dataset (selected as the {label} column).",
                detail={"available_columns": sorted(available)},
            )

    if time_column == target_column:
        raise ValidationError("The time column and target column must be different.")

    dataset.time_column = time_column
    dataset.target_column = target_column
    dataset.frequency = frequency
    dataset.horizon = horizon
    if name:
        dataset.name = name[:200]

                                                                    
    for column in dataset.columns:
        if column.name == time_column:
            column.role = ColumnRole.TIME
        elif column.name == target_column:
            column.role = ColumnRole.TARGET
        elif column.role in (ColumnRole.TIME, ColumnRole.TARGET):
            column.role = ColumnRole.MEASURE

    await session.flush()
    return dataset


def build_profile_response(
    dataset: Dataset, profile: DatasetProfileResult
) -> DatasetProfile:
    cells = max(1, profile.row_count * profile.column_count)

    return DatasetProfile(
        dataset_id=dataset.id,
        row_count=profile.row_count,
        column_count=profile.column_count,
        missing_value_count=profile.missing_value_count,
        missing_value_pct=round(profile.missing_value_count / cells * 100, 3),
        date_range_start=profile.date_range_start,
        date_range_end=profile.date_range_end,
        detected_frequency=profile.detected_frequency,
        columns=[_column_payload(c) for c in profile.columns],
        time_column_suggestions=_suggestions(profile, "time"),
        target_column_suggestions=_suggestions(profile, "target"),
        dimension_suggestions=_suggestions(profile, "dimension"),
        preview_rows=profile.preview_rows,
        warnings=profile.warnings,
    )


def _suggestions(profile: DatasetProfileResult, role: str) -> list[ColumnSuggestion]:
    return [
        ColumnSuggestion(name=name, kind=kind, confidence=confidence, reason=reason)
        for name, kind, confidence, reason in suggestions(profile.columns, role)
    ]


def _column_payload(column) -> dict:  # noqa: ANN001 — ColumnProfile
    return {
        "id": uuid.uuid4(),
        "name": column.name,
        "position": column.position,
        "kind": column.kind,
        "role": column.role,
        "dtype": column.dtype,
        "null_count": column.null_count,
        "distinct_count": column.distinct_count,
        "min_value": column.min_value,
        "max_value": column.max_value,
        "mean_value": column.mean_value,
        "sample_values": column.sample_values,
        "is_date_candidate": column.is_date_candidate,
        "is_target_candidate": column.is_target_candidate,
    }


async def profile_stored(session: AsyncSession, dataset_id: uuid.UUID) -> DatasetProfile:
    dataset = await get_dataset(session, dataset_id)

    if not dataset.columns:
        raise NotFoundError(f"Dataset {dataset_id} has no profiled columns.")

    cells = max(1, dataset.row_count * dataset.column_count)
    columns = sorted(dataset.columns, key=lambda c: c.position)

    def rank(column: DatasetColumn, *, date_axis: bool) -> float:
                                                                          
                                                                  
        base = 0.9 if column.role in (ColumnRole.TIME, ColumnRole.TARGET) else 0.6
        return base if (column.is_date_candidate if date_axis else column.is_target_candidate) else 0.0

    return DatasetProfile(
        dataset_id=dataset.id,
        row_count=dataset.row_count,
        column_count=dataset.column_count,
        missing_value_count=dataset.missing_value_count,
        missing_value_pct=round(dataset.missing_value_count / cells * 100, 3),
        date_range_start=dataset.date_range_start,
        date_range_end=dataset.date_range_end,
        detected_frequency=dataset.frequency,
        columns=[c for c in columns],  # type: ignore[misc] — Pydantic reads them via from_attributes
        time_column_suggestions=[
            ColumnSuggestion(
                name=c.name, kind=c.kind, confidence=rank(c, date_axis=True), reason=c.dtype
            )
            for c in columns
            if c.is_date_candidate
        ],
        target_column_suggestions=[
            ColumnSuggestion(
                name=c.name, kind=c.kind, confidence=rank(c, date_axis=False), reason=c.dtype
            )
            for c in columns
            if c.is_target_candidate
        ],
        dimension_suggestions=[
            ColumnSuggestion(name=c.name, kind=c.kind, confidence=0.7, reason="categorical")
            for c in columns
            if c.role is ColumnRole.DIMENSION
        ],
        preview_rows=[],
        warnings=[],
    )


async def delete_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> None:
    dataset = await get_dataset(session, dataset_id)
    await session.execute(delete(Dataset).where(Dataset.id == dataset.id))


async def count_datasets(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Dataset))
    return int(result.scalar_one())


def dimension_columns(dataset: Dataset) -> list[str]:
    return [c.name for c in dataset.columns if c.role is ColumnRole.DIMENSION]


def guess_segment_columns(dataset: Dataset) -> tuple[str | None, str | None]:
    region_words = ("region", "country", "market", "territory", "geo", "area", "zone")
    category_words = ("category", "product", "segment", "sku", "brand", "line", "type")

    dimensions = dimension_columns(dataset)
    region = next((c for c in dimensions if any(w in c.lower() for w in region_words)), None)
    category = next(
        (c for c in dimensions if c != region and any(w in c.lower() for w in category_words)), None
    )

                                                                      
    remaining = [c for c in dimensions if c not in (region, category)]
    if region is None and remaining:
        region = remaining.pop(0)
    if category is None and remaining:
        category = remaining.pop(0)

    return region, category


def date_bounds(dataset: Dataset) -> tuple[date | None, date | None]:
    return dataset.date_range_start, dataset.date_range_end
