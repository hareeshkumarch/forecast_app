from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import object_store
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.storage import file_exists, remove_file
from app.datasets import quality, queries, refusal
from app.datasets.ingest import persist_upload, write_parquet
from app.datasets.profiler import (
    ColumnProfile,
    DatasetProfileResult,
    profile_frame,
    suggestions,
)
from app.models.entities import Dataset, DatasetColumn
from app.models.enums import (
    ColumnRole,
    DatasetStatus,
    ForecastFrequency,
    GapFill,
    MeasureAggregation,
)
from app.schemas.dataset import ColumnSuggestion, DatasetColumnRead, DatasetProfile

logger = get_logger(__name__)


DATASET_SORTS: dict[str, Any] = {
    "newest": Dataset.created_at.desc(),
    "oldest": Dataset.created_at.asc(),
    "name": Dataset.name.asc(),
    "name_desc": Dataset.name.desc(),
    "rows": Dataset.row_count.desc(),
    "rows_asc": Dataset.row_count.asc(),
    "size": Dataset.file_size_bytes.desc(),
    "size_asc": Dataset.file_size_bytes.asc(),
}
DEFAULT_DATASET_SORT = "newest"
MAX_DATASET_PAGE = settings.api_max_page_size


@dataclass(slots=True)
class DatasetPage:
    rows: list[Dataset]
    total: int
    ready: int
    row_count: int
    file_size_bytes: int


async def list_datasets(
    session: AsyncSession,
    *,
    search: str | None = None,
    sort: str = DEFAULT_DATASET_SORT,
    limit: int = 50,
    offset: int = 0,
) -> DatasetPage:
    where = []
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        where.append(
            or_(
                func.lower(Dataset.name).like(like),
                func.lower(func.coalesce(Dataset.original_filename, "")).like(like),
                func.lower(func.coalesce(Dataset.target_column, "")).like(like),
                func.lower(func.coalesce(Dataset.time_column, "")).like(like),
            )
        )

    totals = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Dataset.status == DatasetStatus.READY),
                func.coalesce(func.sum(Dataset.row_count), 0),
                func.coalesce(func.sum(Dataset.file_size_bytes), 0),
            ).where(*where)
        )
    ).one()

    result = await session.execute(
        select(Dataset)
        .where(*where)
        .order_by(DATASET_SORTS.get(sort, DATASET_SORTS[DEFAULT_DATASET_SORT]), Dataset.id.desc())
        .limit(max(1, min(limit, settings.api_max_page_size)))
        .offset(max(0, offset))
    )

    return DatasetPage(
        rows=list(result.scalars().all()),
        total=int(totals[0]),
        ready=int(totals[1]),
        row_count=int(totals[2]),
        file_size_bytes=int(totals[3]),
    )


async def get_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> Dataset:
    result = await session.execute(
        select(Dataset).options(selectinload(Dataset.columns)).where(Dataset.id == dataset_id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise NotFoundError(f"No dataset with id {dataset_id}.")
    return dataset


def _profile(frame: pl.DataFrame, day_first: bool | None = None) -> DatasetProfileResult:
    return profile_frame(frame, day_first=day_first)


GATED_SERIES_SHOWN = 25


def _intake(profile: DatasetProfileResult, frame: pl.DataFrame) -> refusal.IngestVerdict:
    time_column = next((c.name for c in profile.columns if c.role is ColumnRole.TIME), None)
    dimensions = [c.name for c in profile.columns if c.role is ColumnRole.DIMENSION]
    lengths = (
        refusal.series_lengths_from(frame, time_column, dimensions)
        if time_column is not None
        else {}
    )
    return refusal.assess(profile, frame=frame, dimensions=dimensions, series_lengths=lengths)


def intake_payload(verdict: refusal.IngestVerdict) -> dict[str, Any]:
    payload = verdict.as_dict()
    gated = verdict.gated_series
    payload["gated_series_count"] = len(gated)
    payload["gated_series"] = [gate.as_dict() for gate in gated[:GATED_SERIES_SHOWN]]
    return payload


async def create_from_upload(
    session: AsyncSession,
    content: bytes,
    filename: str,
    *,
    name: str | None = None,
    day_first: bool | None = None,
) -> tuple[Dataset, DatasetProfileResult]:
    dataset_id = uuid.uuid4()

    ingested = await asyncio.to_thread(persist_upload, content, filename, str(dataset_id))
    profile = await asyncio.to_thread(_profile, ingested.frame, day_first)
    readable = profile.normalised if profile.normalised is not None else ingested.frame

    verdict = await asyncio.to_thread(_intake, profile, readable)
    if verdict.verdict is refusal.Verdict.REFUSE:
        await remove_file(ingested.raw_path)
        raise ValidationError(
            " ".join(verdict.refusals), detail={"intake": intake_payload(verdict)}
        )

    # Only now, past the refusal gate. A refused upload is deleted a few lines
    # up, and archiving one would leave a copy of a file the platform decided
    # it could not read. Best-effort: the local file is what the run reads, so
    # an unreachable bucket must not fail an otherwise good upload.
    await object_store.archive_upload(ingested.raw_path, f"uploads/{ingested.raw_path.name}")

    parquet_path = await asyncio.to_thread(write_parquet, readable, str(dataset_id))

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
        intake=intake_payload(verdict),
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

    profile = await asyncio.to_thread(profile_frame, frame)
    frame = profile.normalised if profile.normalised is not None else frame

    verdict = await asyncio.to_thread(_intake, profile, frame)
    if verdict.verdict is refusal.Verdict.REFUSE:
        raise ValidationError(
            " ".join(verdict.refusals), detail={"intake": intake_payload(verdict)}
        )

    parquet_path = await asyncio.to_thread(write_parquet, frame, str(dataset_id))

    time_column = next((c.name for c in profile.columns if c.role is ColumnRole.TIME), None)
    target_column = next((c.name for c in profile.columns if c.role is ColumnRole.TARGET), None)

    dataset = Dataset(
        id=dataset_id,
        name=name[:200],
        original_filename=None,
        source_kind=source_kind,
        intake=intake_payload(verdict),
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
        ForecastFrequency.DAILY: settings.default_horizon_daily,
        ForecastFrequency.WEEKLY: settings.default_horizon_weekly,
        ForecastFrequency.MONTHLY: settings.default_horizon_monthly,
        ForecastFrequency.QUARTERLY: settings.default_horizon_quarterly,
    }.get(frequency or ForecastFrequency.MONTHLY, settings.default_horizon_monthly)


def _attach_columns(session: AsyncSession, dataset: Dataset, profile: DatasetProfileResult) -> None:
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
                parsed_as=column.parsed_as or None,
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


def build_profile_response(dataset: Dataset, profile: DatasetProfileResult) -> DatasetProfile:
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


def _column_payload(column: ColumnProfile) -> dict[str, object]:
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
        return (
            base if (column.is_date_candidate if date_axis else column.is_target_candidate) else 0.0
        )

    return DatasetProfile(
        dataset_id=dataset.id,
        row_count=dataset.row_count,
        column_count=dataset.column_count,
        missing_value_count=dataset.missing_value_count,
        missing_value_pct=round(dataset.missing_value_count / cells * 100, 3),
        date_range_start=dataset.date_range_start,
        date_range_end=dataset.date_range_end,
        detected_frequency=dataset.frequency,
        columns=[DatasetColumnRead.model_validate(column) for column in columns],
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
    files = [dataset.parquet_path, dataset.raw_path]

    await session.execute(delete(Dataset).where(Dataset.id == dataset.id))
    await session.flush()

    for path in files:
        await remove_file(path)


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


async def assess_quality(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    time_column: str,
    target_column: str,
    frequency: ForecastFrequency,
    aggregation: MeasureAggregation,
    gap_fill: GapFill,
) -> quality.QualityReport:
    dataset = await get_dataset(session, dataset_id)

    if not await file_exists(dataset.parquet_path):
        raise ValidationError("This dataset has no stored data file. Re-upload it first.")

    available = {column.name for column in dataset.columns}
    for role, column in (("time", time_column), ("target", target_column)):
        if column not in available:
            raise ValidationError(
                f"'{column}' is not a column in this dataset (selected as the {role} column).",
                detail={"available_columns": sorted(available)},
            )

    def _assess() -> quality.QualityReport:
        series = queries.aggregate_series(
            Path(dataset.parquet_path or ""),
            time_column,
            target_column,
            frequency,
            aggregation=aggregation,
        )
        return quality.build_report(
            rows_scanned=series.rows_scanned,
            rows_usable=series.rows_usable,
            duplicate_rows=series.duplicate_rows,
            row_counts=series.row_counts,
            periods=series.periods,
            values=series.values,
            frequency=frequency,
            fill=gap_fill,
        )

    return await asyncio.to_thread(_assess)
