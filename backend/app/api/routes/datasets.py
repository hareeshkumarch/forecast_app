
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, Response, UploadFile, status

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.errors import PayloadTooLargeError, ValidationError
from app.schemas.dataset import (
    DatasetConfigureRequest,
    DatasetDetail,
    DatasetProfile,
    DatasetRead,
    DatasetUploadResponse,
)
from app.services import dataset_service

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("", response_model=list[DatasetRead], summary="List datasets")
async def list_datasets(session: SessionDep) -> list[DatasetRead]:
    datasets = await dataset_service.list_datasets(session)
    return [DatasetRead.model_validate(d) for d in datasets]


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
        session, content, file.filename, name=name
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
