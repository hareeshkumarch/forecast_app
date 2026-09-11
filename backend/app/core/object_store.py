from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 30.0

_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}

_client: Any = None
_client_lock = threading.Lock()


def configured() -> bool:
    return bool(
        settings.storage_bucket
        and settings.storage_endpoint
        and settings.storage_access_key_id
        and settings.storage_secret_access_key
    )


def _build_client() -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.storage_endpoint,
        aws_access_key_id=settings.storage_access_key_id,
        aws_secret_access_key=settings.storage_secret_access_key,
        region_name=settings.storage_region,
        config=Config(
            signature_version="s3v4",
            connect_timeout=_TIMEOUT_SECONDS,
            read_timeout=_TIMEOUT_SECONDS,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def _client_once() -> Any:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _build_client()
    return _client


def reset_client() -> None:
    global _client
    with _client_lock:
        _client = None


def _put(path: Path, key: str) -> None:
    body = path.read_bytes()
    _client_once().put_object(
        Bucket=settings.storage_bucket,
        Key=key,
        Body=body,
        ContentType=_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
    )


async def archive_upload(path: Path, key: str) -> bool:
    if not configured():
        return False

    try:
        await asyncio.to_thread(_put, path, key)
    except OSError as exc:
        logger.warning("Could not read %s to archive it: %s", path, exc)
        return False
    except Exception as exc:
        logger.warning("Archiving %s to bucket %s failed: %s", key, settings.storage_bucket, exc)
        return False

    logger.info("Archived %s to bucket %s", key, settings.storage_bucket)
    return True
