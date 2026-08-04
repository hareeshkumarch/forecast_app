from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.security import using_insecure_default_key
from app.database.base import utcnow

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: str
    storage_writable: bool
    forecast_workers: int
    max_upload_mb: float

    using_default_credential_key: bool
    timestamp: str


@router.get("/health", response_model=HealthResponse, summary="Service health")
async def health(session: SessionDep) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:
        database = f"error: {type(exc).__name__}"

    try:
        settings.ensure_directories()
        probe = settings.exports_dir / ".health"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        storage_writable = True
    except Exception:
        storage_writable = False

    return HealthResponse(
        status="ok" if database == "ok" and storage_writable else "degraded",
        database=database,
        storage_writable=storage_writable,
        forecast_workers=settings.forecast_workers,
        max_upload_mb=round(settings.max_upload_bytes / (1024 * 1024), 2),
        using_default_credential_key=using_insecure_default_key(),
        timestamp=utcnow().isoformat(),
    )
