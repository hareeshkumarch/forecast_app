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

# SQLite by default, because the suite has to be runnable with nothing
# installed. It is also more forgiving than what the platform actually runs on:
# it will store a NaN metric or an -Infinity inside a JSON column quite
# happily, and Postgres rejects both outright. Set RUN_AGAINST_POSTGRES to
# point the same tests at the real thing.
if os.environ.get("RUN_AGAINST_POSTGRES") != "1":
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_STORAGE / 'test.db').as_posix()}"

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database.base import Base  # noqa: E402
from app.database.session import SessionFactory, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def storage_root() -> Path:
    return _STORAGE


@pytest.fixture(autouse=True)
async def _schema() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    # Every test gets its own event loop, and a pooled asyncpg connection
    # belongs to the loop that opened it — reusing one across tests raises
    # "attached to a different loop" on the second. SQLite does not care;
    # Postgres does, and the point of running these against Postgres is that
    # it does not behave like SQLite.
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
