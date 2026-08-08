from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.errors import PayloadTooLargeError, ValidationError
from app.models.enums import ForecastFrequency, GapFill, MeasureAggregation
from app.schemas.dataset import (
    DataQualityResponse,
    DatasetConfigureRequest,
    DatasetDetail,
    DatasetPage,
    DatasetProfile,
    DatasetRead,
    DatasetUploadResponse,
)
from app.services import dataset_service

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("", response_model=DatasetPage, summary="List datasets")
async def list_datasets(
    session: SessionDep,
    search: str | None = Query(default=None, max_length=200),
    sort: str = Query(
        default=dataset_service.DEFAULT_DATASET_SORT,
        description=f"One of: {', '.join(dataset_service.DATASET_SORTS)}.",
    ),
    limit: int = Query(default=50, ge=1, le=dataset_service.MAX_DATASET_PAGE),
    offset: int = Query(default=0, ge=0),
) -> DatasetPage:
    page = await dataset_service.list_datasets(
        session, search=search, sort=sort, limit=limit, offset=offset
    )
    return DatasetPage(
        total=page.total,
        limit=limit,
        offset=offset,
        sort=sort
        if sort in dataset_service.DATASET_SORTS
        else dataset_service.DEFAULT_DATASET_SORT,
        ready=page.ready,
        row_count=page.row_count,
        file_size_bytes=page.file_size_bytes,
        rows=[DatasetRead.model_validate(d) for d in page.rows],
    )


@router.post(
    "/upload",
    response_model=DatasetUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV or XLSX dataset",
)
async def upload_dataset(
    session: SessionDep,
    file: UploadFile = File(..., description="CSV or XLSX, 20 MB maximum."),
    name: str | None = Form(default=None),
    date_order: Literal["auto", "day_first", "month_first"] = Form(default="auto"),
) -> DatasetUploadResponse:
    """Upload a file and read its schema.

    `date_order` settles slash dates the data cannot settle itself: 01/02/2024
    is the first of February in most of the world and the second of January in
    the United States. Left on "auto" the column decides, and the profile says
    so when it had to guess.
    """
    if not file.filename:
        raise ValidationError("The upload is missing a filename.")

    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > settings.max_upload_bytes:
            limit_mb = settings.max_upload_bytes / (1024 * 1024)
            raise PayloadTooLargeError(
                f"The file exceeds the {limit_mb:.0f} MB limit. "
                "Filter or aggregate the data before uploading.",
                detail={"limit_bytes": settings.max_upload_bytes},
            )
        chunks.append(chunk)

    content = b"".join(chunks)

    dataset, profile = await dataset_service.create_from_upload(
        session,
        content,
        file.filename,
        name=name,
        day_first={"day_first": True, "month_first": False}.get(date_order),
    )

    return DatasetUploadResponse(
        dataset=DatasetDetail.model_validate(dataset),
        profile=dataset_service.build_profile_response(dataset, profile),
    )


@router.get("/{dataset_id}", response_model=DatasetDetail, summary="Get a dataset")
async def get_dataset(dataset_id: uuid.UUID, session: SessionDep) -> DatasetDetail:
    dataset = await dataset_service.get_dataset(session, dataset_id)
    return DatasetDetail.model_validate(dataset)


@router.get(
    "/{dataset_id}/profile", response_model=DatasetProfile, summary="Get the dataset profile"
)
async def get_profile(dataset_id: uuid.UUID, session: SessionDep) -> DatasetProfile:
    return await dataset_service.profile_stored(session, dataset_id)


@router.patch(
    "/{dataset_id}",
    response_model=DatasetDetail,
    summary="Set the time column, target, frequency and horizon",
)
async def configure_dataset(
    dataset_id: uuid.UUID, payload: DatasetConfigureRequest, session: SessionDep
) -> DatasetDetail:
    dataset = await dataset_service.configure(
        session,
        dataset_id,
        time_column=payload.time_column,
        target_column=payload.target_column,
        frequency=payload.frequency,
        horizon=payload.horizon,
        name=payload.name,
    )
    return DatasetDetail.model_validate(dataset)


@router.delete(
    "/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a dataset",
)
async def delete_dataset(dataset_id: uuid.UUID, session: SessionDep) -> Response:
    await dataset_service.delete_dataset(session, dataset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{dataset_id}/quality",
    response_model=DataQualityResponse,
    summary="Assess a column and frequency choice before running a forecast",
)
async def dataset_quality(
    dataset_id: uuid.UUID,
    session: SessionDep,
    time_column: str,
    target_column: str,
    frequency: ForecastFrequency = ForecastFrequency.MONTHLY,
    aggregation: MeasureAggregation = MeasureAggregation.SUM,
    gap_fill: GapFill = GapFill.AUTO,
) -> DataQualityResponse:
    report = await dataset_service.assess_quality(
        session,
        dataset_id,
        time_column=time_column,
        target_column=target_column,
        frequency=frequency,
        aggregation=aggregation,
        gap_fill=gap_fill,
    )

    return DataQualityResponse(
        dataset_id=dataset_id,
        time_column=time_column,
        target_column=target_column,
        frequency=frequency,
        aggregation=aggregation,
        gap_fill=gap_fill,
        range_start=report.range_start,
        range_end=report.range_end,
        coverage=round(report.coverage, 4),
        blocked=report.blocked,
        issues=[issue.as_dict() for issue in report.issues],
        rows_scanned=report.rows_scanned,
        rows_usable=report.rows_usable,
        periods_present=report.periods_present,
        periods_expected=report.periods_expected,
        gap_count=report.gap_count,
        longest_gap=report.longest_gap,
        duplicate_rows=report.duplicate_rows,
        partial_periods=report.partial_periods,
        outlier_periods=report.outlier_periods,
        negative_periods=report.negative_periods,
        zero_periods=report.zero_periods,
        constant_target=report.constant_target,
        fill_applied=report.fill_applied,
    )
