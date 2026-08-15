"""The archive is a backup, and the tests that matter are the ones proving it
behaves like one: silent when unconfigured, and never able to fail an upload
that otherwise succeeded."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.core import object_store
from app.core.config import settings


@pytest.fixture
def upload(tmp_path: Path) -> Path:
    path = tmp_path / "sales.csv"
    path.write_bytes(b"period,units\n2026-01-01,10\n")
    return path


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co", raising=False)
    monkeypatch.setattr(settings, "storage_bucket", "file", raising=False)
    monkeypatch.setattr(settings, "storage_api_key", "test-key", raising=False)


def _transport(handler) -> object:
    """Swap httpx's network for a handler, without touching call sites."""

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    return Client


# --------------------------------------------------------------- unconfigured


async def test_an_unconfigured_platform_archives_nothing(upload: Path) -> None:
    # The single-node default: no bucket, no key, no network call, no noise.
    assert object_store.configured() is False
    assert await object_store.archive_upload(upload, "uploads/sales.csv") is False


async def test_a_bucket_without_a_key_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, upload: Path
) -> None:
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co", raising=False)
    monkeypatch.setattr(settings, "storage_bucket", "file", raising=False)
    monkeypatch.setattr(settings, "storage_api_key", "", raising=False)
    # Half-configured is unconfigured, rather than a request guaranteed to 401.
    assert await object_store.archive_upload(upload, "uploads/sales.csv") is False


# ------------------------------------------------------------------- the happy


async def test_it_puts_the_file_in_the_bucket(
    monkeypatch: pytest.MonkeyPatch, configured: None, upload: Path
) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        seen["type"] = request.headers.get("content-type")
        seen["auth"] = request.headers.get("authorization")
        seen["upsert"] = request.headers.get("x-upsert")
        return httpx.Response(200, json={"Key": "file/uploads/sales.csv"})

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))

    assert await object_store.archive_upload(upload, "uploads/sales.csv") is True
    assert seen["url"] == "https://project.supabase.co/storage/v1/object/file/uploads/sales.csv"
    assert seen["body"] == upload.read_bytes()
    assert seen["type"] == "text/csv"
    assert seen["auth"] == "Bearer test-key"
    # Re-uploading the same dataset id should replace rather than collide.
    assert seen["upsert"] == "true"


async def test_a_spreadsheet_keeps_its_own_content_type(
    monkeypatch: pytest.MonkeyPatch, configured: None, tmp_path: Path
) -> None:
    path = tmp_path / "sales.xlsx"
    path.write_bytes(b"PK\x03\x04")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["type"] = request.headers.get("content-type")
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))

    assert await object_store.archive_upload(path, "uploads/sales.xlsx") is True
    assert seen["type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ------------------------------------------------------------ nothing may raise


@pytest.mark.parametrize("status", [401, 403, 404, 413, 500])
async def test_a_refusal_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, configured: None, upload: Path, status: int
) -> None:
    # A missing bucket, a key without insert rights and a Supabase outage all
    # arrive here. None of them may fail an upload that already parsed and
    # stored locally.
    monkeypatch.setattr(
        httpx, "AsyncClient", _transport(lambda _r: httpx.Response(status, text="nope"))
    )
    assert await object_store.archive_upload(upload, "uploads/sales.csv") is False


async def test_a_network_failure_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, configured: None, upload: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    assert await object_store.archive_upload(upload, "uploads/sales.csv") is False


async def test_a_missing_local_file_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, configured: None, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        httpx, "AsyncClient", _transport(lambda _r: httpx.Response(200))
    )
    assert await object_store.archive_upload(tmp_path / "gone.csv", "uploads/gone.csv") is False


async def test_a_bucket_name_needing_escaping_is_escaped(
    monkeypatch: pytest.MonkeyPatch, configured: None, upload: Path
) -> None:
    monkeypatch.setattr(settings, "storage_bucket", "my bucket", raising=False)
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    await object_store.archive_upload(upload, "uploads/sales.csv")
    assert "my%20bucket" in str(seen["url"])
