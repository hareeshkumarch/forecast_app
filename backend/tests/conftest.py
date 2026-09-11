from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

_STORAGE = Path(tempfile.mkdtemp(prefix="fp-tests-"))
os.environ["STORAGE_ROOT"] = str(_STORAGE)
os.environ["FORECAST_WORKERS"] = "1"
os.environ["CREDENTIAL_SECRET_KEY"] = "test-key-not-a-real-secret"

_SQLITE_DB: Path | None = None
if os.environ.get("RUN_AGAINST_POSTGRES") != "1":
    _SQLITE_DB = _STORAGE / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_SQLITE_DB.as_posix()}"

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database.base import Base  # noqa: E402
from app.database.session import SessionFactory, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _authentication_stays_off():
    from app.core.config import settings

    before = (settings.auth_enabled, settings.auth_require_approval)
    yield
    settings.auth_enabled, settings.auth_require_approval = before


@pytest.fixture(scope="session")
def storage_root() -> Path:
    return _STORAGE


@pytest.fixture(autouse=True)
def _rate_limits_start_fresh():
    from app.core.ratelimit import limiter

    limiter.forget_all()
    yield
    limiter.forget_all()


@pytest.fixture(autouse=True)
def _process_wide_state_starts_fresh():
    from app.core import auth, breaker, cache, lifecycle, metrics, streams
    from app.services import capacity_service
    from app.services.job_runner import scheduler

    cache.clear_all()
    breaker.reset_all()
    metrics.registry.reset()
    streams.registry.forget_all()
    scheduler.forget_all()
    capacity_service.forget()
    lifecycle.reset()
    auth.reset_caches()
    yield
    cache.clear_all()
    breaker.reset_all()
    streams.registry.forget_all()
    scheduler.forget_all()
    capacity_service.forget()
    lifecycle.reset()
    auth.reset_caches()


async def _reset_schema() -> None:
    await engine.dispose()

    if _SQLITE_DB is None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        return

    for suffix in ("", "-wal", "-shm"):
        _SQLITE_DB.with_name(_SQLITE_DB.name + suffix).unlink(missing_ok=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture(autouse=True)
async def _schema() -> AsyncIterator[None]:
    await _reset_schema()
    yield
    await engine.dispose()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as db_session:
        yield db_session
        await db_session.rollback()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=180) as http:
        yield http
