from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core import object_store
from app.core.config import settings


@pytest.fixture(autouse=True)
def _fresh_client() -> Any:
    object_store.reset_client()
    yield
    object_store.reset_client()


@pytest.fixture
def upload(tmp_path: Path) -> Path:
    path = tmp_path / "sales.csv"
    path.write_bytes(b"period,units\n2026-01-01,10\n")
    return path


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "storage_bucket", "file", raising=False)
    monkeypatch.setattr(
        settings,
        "storage_endpoint",
        "https://project.storage.supabase.co/storage/v1/s3",
        raising=False,
    )
    monkeypatch.setattr(settings, "storage_access_key_id", "key-id", raising=False)
    monkeypatch.setattr(settings, "storage_secret_access_key", "secret", raising=False)
    monkeypatch.setattr(settings, "storage_region", "ap-south-1", raising=False)


class _Recorder:
    def __init__(self, raises: Exception | None = None) -> None:
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return {"ETag": '"abc"'}


def _use(monkeypatch: pytest.MonkeyPatch, client: _Recorder) -> None:
    monkeypatch.setattr(object_store, "_build_client", lambda: client)


async def test_an_unconfigured_platform_archives_nothing(upload: Path) -> None:
    assert object_store.configured() is False
    assert await object_store.archive_upload(upload, "uploads/sales.csv") is False


async def test_a_bucket_without_credentials_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, upload: Path
) -> None:
    monkeypatch.setattr(settings, "storage_bucket", "file", raising=False)
    monkeypatch.setattr(settings, "storage_endpoint", "https://x/storage/v1/s3", raising=False)
    monkeypatch.setattr(settings, "storage_access_key_id", "", raising=False)
    monkeypatch.setattr(settings, "storage_secret_access_key", "", raising=False)
    assert await object_store.archive_upload(upload, "uploads/sales.csv") is False


async def test_it_puts_the_file_in_the_bucket(
    monkeypatch: pytest.MonkeyPatch, configured: None, upload: Path
) -> None:
    client = _Recorder()
    _use(monkeypatch, client)

    assert await object_store.archive_upload(upload, "uploads/sales.csv") is True
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["Bucket"] == "file"
    assert call["Key"] == "uploads/sales.csv"
    assert call["Body"] == upload.read_bytes()
    assert call["ContentType"] == "text/csv"


async def test_a_spreadsheet_keeps_its_own_content_type(
    monkeypatch: pytest.MonkeyPatch, configured: None, tmp_path: Path
) -> None:
    path = tmp_path / "sales.xlsx"
    path.write_bytes(b"PK\x03\x04")
    client = _Recorder()
    _use(monkeypatch, client)

    assert await object_store.archive_upload(path, "uploads/sales.xlsx") is True
    assert client.calls[0]["ContentType"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


async def test_an_unknown_suffix_falls_back_to_octet_stream(
    monkeypatch: pytest.MonkeyPatch, configured: None, tmp_path: Path
) -> None:
    path = tmp_path / "sales.parquet"
    path.write_bytes(b"PAR1")
    client = _Recorder()
    _use(monkeypatch, client)

    assert await object_store.archive_upload(path, "uploads/sales.parquet") is True
    assert client.calls[0]["ContentType"] == "application/octet-stream"


async def test_the_client_is_built_once_and_reused(
    monkeypatch: pytest.MonkeyPatch, configured: None, upload: Path
) -> None:
    built = 0
    client = _Recorder()

    def build() -> _Recorder:
        nonlocal built
        built += 1
        return client

    monkeypatch.setattr(object_store, "_build_client", build)

    for _ in range(3):
        assert await object_store.archive_upload(upload, "uploads/sales.csv") is True
    assert built == 1
    assert len(client.calls) == 3


async def test_a_refusal_from_storage_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, configured: None, upload: Path
) -> None:
    _use(monkeypatch, _Recorder(raises=RuntimeError("AccessDenied")))
    assert await object_store.archive_upload(upload, "uploads/sales.csv") is False


async def test_a_network_failure_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, configured: None, upload: Path
) -> None:
    _use(monkeypatch, _Recorder(raises=ConnectionError("unreachable")))
    assert await object_store.archive_upload(upload, "uploads/sales.csv") is False


async def test_a_missing_local_file_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, configured: None, tmp_path: Path
) -> None:
    _use(monkeypatch, _Recorder())
    assert await object_store.archive_upload(tmp_path / "gone.csv", "uploads/gone.csv") is False


async def test_a_broken_client_build_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, configured: None, upload: Path
) -> None:
    def explode() -> Any:
        raise ValueError("Invalid endpoint")

    monkeypatch.setattr(object_store, "_build_client", explode)
    assert await object_store.archive_upload(upload, "uploads/sales.csv") is False
