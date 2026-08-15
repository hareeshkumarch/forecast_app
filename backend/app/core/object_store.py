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

Spoken over S3 rather than Supabase's own REST API, because the credential
that fits is a storage-scoped S3 access key. The alternative is the service
role key, which bypasses row-level security across the entire database — far
more authority than "may write one bucket" needs. The same code therefore
works against real S3, MinIO, or any other S3-compatible endpoint.

Best-effort by construction. A dataset that parsed and stored locally is a
successful upload; failing it because storage was briefly unreachable would
trade a working feature for a backup. Failures log and return False.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Long enough for a 20 MB upload on a slow link, short enough that an
#: unreachable endpoint cannot hold a request open indefinitely.
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
    """Whether an archive destination has been set up at all."""
    return bool(
        settings.storage_bucket
        and settings.storage_endpoint
        and settings.storage_access_key_id
        and settings.storage_secret_access_key
    )


def _build_client() -> Any:
    # Imported here, not at module scope: the platform runs without an archive
    # configured by default, and an optional feature should not make its
    # dependency a hard import for every process that starts.
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
            # One attempt plus one retry. This is a backup: it should not sit
            # in front of an upload response retrying a dead endpoint.
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def _client_once() -> Any:
    """One client for the process. Building one parses botocore's data files,
    which is far too much work to repeat per upload."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _build_client()
    return _client


def reset_client() -> None:
    """Drop the memoised client. For tests, and for a settings reload."""
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
    """Copy a stored upload to the configured bucket. Never raises.

    Returns True only when the object is known to be stored, so a caller can
    record provenance honestly rather than assuming.
    """
    if not configured():
        return False

    try:
        await asyncio.to_thread(_put, path, key)
    except OSError as exc:
        logger.warning("Could not read %s to archive it: %s", path, exc)
        return False
    except Exception as exc:
        # Deliberately broad. A missing bucket, a key without write rights, a
        # bad endpoint and a network partition all arrive here as different
        # botocore types, and none of them may fail an upload that already
        # parsed and stored locally.
        logger.warning("Archiving %s to bucket %s failed: %s", key, settings.storage_bucket, exc)
        return False

    logger.info("Archived %s to bucket %s", key, settings.storage_bucket)
    return True
