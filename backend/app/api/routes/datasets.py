from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.errors import PayloadTooLargeError, ValidationError
from app.models.enums import ForecastFrequency, GapFill, MeasureAggregation
from app.schema import coverage
from app.schema.contract import MappingProposal
from app.schemas.dataset import (
    CoverageResponse,
    CoverageRowRead,
    DataQualityResponse,
    DatasetConfigureRequest,
    DatasetDetail,
    DatasetPage,
    DatasetProfile,
    DatasetRead,
    DatasetUploadResponse,
    MappingAcceptRequest,
    MappingProposalRead,
)
from app.services import dataset_service, mapping_service, user_service

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
    description=(
        "`date_order` settles slash dates the data cannot settle itself: 01/02/2024 is the "
        "first of February in most of the world and the second of January in the United "
        "States. Left on 'auto' the column decides, and the profile says when it had to "
        "guess. A file that cannot be forecast at all is refused with the reasons; one that "
        "is merely ambiguous comes back with questions to answer."
    ),
)
async def upload_dataset(
    session: SessionDep,
    user: CurrentUser,
    file: UploadFile = File(..., description="CSV or XLSX, 20 MB maximum."),
    name: str | None = Form(default=None),
    date_order: Literal["auto", "day_first", "month_first"] = Form(default="auto"),
) -> DatasetUploadResponse:
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
        created_by_user_id=await user_service.owner_id(session, user),
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


def _mapping_response(dataset_id: uuid.UUID, proposal: MappingProposal) -> MappingProposalRead:
    return MappingProposalRead(dataset_id=dataset_id, **proposal.as_dict())  # type: ignore[arg-type]


@router.get(
    "/{dataset_id}/mapping",
    response_model=MappingProposalRead,
    summary="Propose which columns hold the dates, the target and the series keys",
    description=(
        "Reads the stored table and returns the mapping it proposes: the date and target "
        "columns, the dimension columns whose combination makes one row per period, the "
        "covariates, the frequency and how duplicate rows would be combined — with a "
        "confidence and the ranked runners-up for every role. Nothing is fitted here. A "
        "schema accepted before is returned as remembered rather than re-inferred, and "
        "`needs_confirmation` says when the layer refuses to guess."
    ),
)
async def get_mapping(dataset_id: uuid.UUID, session: SessionDep) -> MappingProposalRead:
    proposal = await mapping_service.proposal_for(session, dataset_id)
    return _mapping_response(dataset_id, proposal)


@router.post(
    "/{dataset_id}/mapping",
    response_model=MappingProposalRead,
    summary="Accept or override the proposed mapping",
    description=(
        "Stores the mapping against the file's schema fingerprint — sorted column names and "
        "dtypes — so the next upload of the same export is mapped without asking, and points "
        "the dataset's time column, target column and frequency at what was accepted."
    ),
)
async def accept_mapping(
    dataset_id: uuid.UUID, payload: MappingAcceptRequest, session: SessionDep
) -> MappingProposalRead:
    proposal = await mapping_service.accept(
        session,
        dataset_id,
        {
            "date_col": payload.date_col,
            "target_col": payload.target_col,
            "series_keys": payload.series_keys,
            "covariates": payload.covariates,
            "frequency": payload.frequency,
            "aggregation": payload.aggregation,
        },
    )
    return _mapping_response(dataset_id, proposal)


@router.get(
    "/{dataset_id}/coverage",
    response_model=CoverageResponse,
    summary="What the file actually holds, series by period",
    description=(
        "A grid of every series against every period the frequency implies, so ragged "
        "starts, mid-history gaps and runs of zeros are visible before a run is paid for. "
        "Null means the series has no row for that period, which is a different fact from "
        "a reported zero. Bounded: the patchiest series are kept when there are more than "
        "the grid can carry, and the most recent periods when the calendar is longer."
    ),
)
async def dataset_coverage(
    dataset_id: uuid.UUID,
    session: SessionDep,
    max_series: int = Query(default=coverage.DEFAULT_MAX_SERIES, ge=1, le=400),
    max_periods: int = Query(default=coverage.DEFAULT_MAX_PERIODS, ge=1, le=400),
) -> CoverageResponse:
    matrix = await mapping_service.coverage_for(
        session, dataset_id, max_series=max_series, max_periods=max_periods
    )
    return CoverageResponse(
        dataset_id=dataset_id,
        frequency=matrix.frequency,
        periods=matrix.periods,
        rows=[CoverageRowRead(**row.as_dict()) for row in matrix.rows],
        series_total=matrix.series_total,
        series_shown=len(matrix.rows),
        periods_total=matrix.periods_total,
        required_history=matrix.required_history,
        series_truncated=matrix.series_truncated,
        periods_truncated=matrix.periods_truncated,
    )
