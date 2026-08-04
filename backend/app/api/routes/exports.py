
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Query
from starlette.responses import FileResponse

from app.api.deps import SessionDep
from app.core.errors import NotFoundError
from app.models.enums import ExportFormat
from app.reporting import exporter
from app.services import forecast_service

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get(
    "/{forecast_id}",
    summary="Export a forecast run",
    response_class=FileResponse,
)
async def export_forecast(
    forecast_id: uuid.UUID,
    session: SessionDep,
    format: ExportFormat = Query(  # noqa: A002 — matches the public query-param name
        default=ExportFormat.CSV, description="csv, xlsx or json."
    ),
) -> FileResponse:
    run = await forecast_service.get_run(session, forecast_id)
    job = await exporter.create_export(session, forecast_id, format)

    if not job.file_path or not Path(job.file_path).exists():
        raise NotFoundError("The export file could not be found after generation.")

                                                                               
    await session.commit()

    return FileResponse(
        path=job.file_path,
        media_type=exporter.export_media_type(format),
        filename=exporter.export_filename(run, format),
    )
