from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import polars as pl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.entities import Dataset, SchemaMapping
from app.schema.canonical import CanonicalConfig, to_canonical
from app.schema.contract import SOURCE_OVERRIDE, MappingProposal
from app.schema.coverage import (
    DEFAULT_MAX_PERIODS,
    DEFAULT_MAX_SERIES,
    CoverageMatrix,
    coverage_matrix,
)
from app.schema.resolve import apply_override, fingerprint_of, prepare, propose
from app.schema.validation import ValidationReport, validate_canonical
from app.services import dataset_service


async def proposal_for(
    session: AsyncSession, dataset_id: uuid.UUID, *, use_memory: bool = True
) -> MappingProposal:
    frame = await _frame_of(session, dataset_id)
    remembered = await _remembered(session, frame) if use_memory else None
    proposal, _ = await asyncio.to_thread(propose, frame, remembered=remembered)
    return proposal


async def report_for(
    session: AsyncSession, dataset_id: uuid.UUID, proposal: MappingProposal
) -> ValidationReport:
    frame = await _frame_of(session, dataset_id)
    working, _, _ = await asyncio.to_thread(prepare, frame)
    config = CanonicalConfig.from_proposal(proposal)
    canonical = await asyncio.to_thread(to_canonical, working, config)
    return await asyncio.to_thread(
        validate_canonical, canonical, frequency=config.frequency, covariates=config.covariates
    )


async def coverage_for(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    max_series: int = DEFAULT_MAX_SERIES,
    max_periods: int = DEFAULT_MAX_PERIODS,
) -> CoverageMatrix:
    frame = await _frame_of(session, dataset_id)
    remembered = await _remembered(session, frame)
    proposal, working = await asyncio.to_thread(propose, frame, remembered=remembered)

    config = CanonicalConfig.from_proposal(proposal)
    canonical = await asyncio.to_thread(to_canonical, working, config)
    report = await asyncio.to_thread(
        validate_canonical, canonical, frequency=config.frequency, covariates=config.covariates
    )
    return await asyncio.to_thread(
        coverage_matrix, canonical, report, max_series=max_series, max_periods=max_periods
    )


async def accept(
    session: AsyncSession, dataset_id: uuid.UUID, override: dict[str, object]
) -> MappingProposal:
    frame = await _frame_of(session, dataset_id)
    proposal, _ = await asyncio.to_thread(propose, frame)
    apply_override(proposal, override, source=SOURCE_OVERRIDE)

    if not proposal.complete:
        raise ValidationError(
            "An accepted mapping needs both a date column and a target column.",
            detail={"code": "incomplete_mapping", "mapping": proposal.as_dict()},
        )

    named = [
        name
        for name in (
            proposal.date_col,
            proposal.target_col,
            *proposal.series_keys,
            *proposal.covariates,
        )
        if name is not None
    ]
    unknown = [name for name in named if name not in frame.columns]
    if unknown:
        raise ValidationError(
            f"The mapping names column(s) this dataset does not have: {', '.join(unknown)}.",
            detail={"code": "unknown_column", "columns": unknown},
        )

    await remember(session, proposal, frame, dataset_id=dataset_id)

    dataset = await dataset_service.get_dataset(session, dataset_id)
    dataset.time_column = proposal.date_col
    dataset.target_column = proposal.target_col
    if proposal.frequency is not None:
        dataset.frequency = proposal.frequency
    await session.flush()

    return proposal


async def remember(
    session: AsyncSession,
    proposal: MappingProposal,
    frame: pl.DataFrame,
    *,
    dataset_id: uuid.UUID | None = None,
) -> SchemaMapping:
    stored = await session.scalar(
        select(SchemaMapping).where(SchemaMapping.fingerprint == proposal.fingerprint)
    )
    if stored is None:
        stored = SchemaMapping(fingerprint=proposal.fingerprint)
        session.add(stored)

    stored.date_col = str(proposal.date_col)
    stored.target_col = str(proposal.target_col)
    stored.series_keys = list(proposal.series_keys)
    stored.covariates = list(proposal.covariates)
    stored.frequency = proposal.frequency
    stored.aggregation = proposal.aggregation
    stored.columns = {name: str(dtype) for name, dtype in frame.schema.items()}
    stored.accepted_from_dataset_id = dataset_id
    await session.flush()
    return stored


async def remembered_for(session: AsyncSession, frame: pl.DataFrame) -> dict[str, object] | None:
    return await _remembered(session, frame)


async def _remembered(session: AsyncSession, frame: pl.DataFrame) -> dict[str, object] | None:
    stored = await session.scalar(
        select(SchemaMapping).where(SchemaMapping.fingerprint == fingerprint_of(frame))
    )
    if stored is None:
        return None
    return {
        "date_col": stored.date_col,
        "target_col": stored.target_col,
        "series_keys": list(stored.series_keys or []),
        "covariates": list(stored.covariates or []),
        "frequency": stored.frequency,
        "aggregation": stored.aggregation,
    }


async def _frame_of(session: AsyncSession, dataset_id: uuid.UUID) -> pl.DataFrame:
    dataset = await dataset_service.get_dataset(session, dataset_id)
    return await asyncio.to_thread(_read_frame, dataset)


def _read_frame(dataset: Dataset) -> pl.DataFrame:
    path = Path(dataset.parquet_path or "")
    if not dataset.parquet_path or not path.exists():
        raise NotFoundError(f"Dataset {dataset.id} has no stored table to map.")
    return pl.read_parquet(path)
