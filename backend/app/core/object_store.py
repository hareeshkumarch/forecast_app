"""Off-box archival of the one file that cannot be regenerated.

A dataset upload is the customer's original spreadsheet. Everything else the
platform writes — the Parquet it reads during a run, the exports it renders —
is derived from that upload and can be rebuilt from it. So the upload is the
only artifact whose loss is permanent, and the only one worth paying a network
round trip to copy somewhere the instance's lifetime does not bound.

Deliberately *archival* rather than primary. The read path still opens the
local file: the forecasting engine has a 60-second budget with 28 seconds of
it in fitting, and putting object storage in front of the Parquet it reads
would spend that budget on transfers. This copies, it does not relocate.

Best-effort by construction. A dataset that parsed and stored locally is a
successful upload; failing it because Supabase Storage was briefly unreachable
would trade a working feature for a backup. Failures log and return False.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Long enough for a 20 MB upload on a slow link, short enough that an
#: unreachable Supabase cannot hold the request open indefinitely.
_TIMEOUT_SECONDS = 30.0

_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}


def configured() -> bool:
    """Whether an archive destination has been set up at all."""
    return bool(settings.supabase_url and settings.storage_bucket and settings.storage_api_key)


def _endpoint(key: str) -> str:
    base = settings.supabase_url.rstrip("/")
    bucket = quote(settings.storage_bucket, safe="")
    return f"{base}/storage/v1/object/{bucket}/{quote(key, safe='/')}"


async def archive_upload(path: Path, key: str) -> bool:
    """Copy a stored upload to the configured bucket. Never raises.

    Returns True only when the object is known to be stored, so a caller can
    record provenance honestly rather than assuming.
    """
    if not configured():
        return False

    try:
        payload = await _read(path)
    except OSError as exc:
        logger.warning("Could not read %s to archive it: %s", path, exc)
        return False

    content_type = _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
    headers = {
        "apikey": settings.storage_api_key,
        "Authorization": f"Bearer {settings.storage_api_key}",
        "Content-Type": content_type,
        # Re-uploading a dataset id should replace, not collide. Datasets are
        # keyed by uuid, so this only fires on a genuine retry of the same one.
        "x-upsert": "true",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(_endpoint(key), content=payload, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("Archiving %s to bucket %s failed: %s", key, settings.storage_bucket, exc)
        return False

    if response.status_code >= 400:
        # The body carries Supabase's own reason — a missing bucket and a key
        # without insert rights fail identically at the status code alone.
        logger.warning(
            "Archiving %s to bucket %s returned %s: %s",
            key,
            settings.storage_bucket,
            response.status_code,
            response.text[:200],
        )
        return False

    logger.info("Archived %s to bucket %s", key, settings.storage_bucket)
    return True


async def _read(path: Path) -> bytes:
    import asyncio

    return await asyncio.to_thread(path.read_bytes)
