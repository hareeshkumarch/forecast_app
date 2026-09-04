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
    """No test leaves the auth switches flipped for the next one.

    `settings` is a single object for the whole session, so a test that turns
    authentication on and forgets to turn it off does not fail itself — it
    fails every test that runs after it, in files it has nothing to do with,
    with a 401 that reads as a broken endpoint. That cost an afternoon once;
    it does not get to cost another.
    """
    from app.core.config import settings

    before = (settings.auth_enabled, settings.auth_require_approval)
    yield
    settings.auth_enabled, settings.auth_require_approval = before


@pytest.fixture(scope="session")
def storage_root() -> Path:
    return _STORAGE


@pytest.fixture(autouse=True)
def _rate_limits_start_fresh():
    """Each test gets its own allowance.

    Every request in this suite arrives from the same place as far as the
    limiter is concerned, so without this they all share one window: the run
    is fine for the first two hundred and forty requests and then fails
    whatever happens to be running when the allowance runs out. That is a
    different set of tests each time, in files that have nothing to do with
    rate limiting, answering 429 where they expected a result — the same shape
    of afternoon as the auth switches above.

    Cleared rather than switched off, so the middleware stays in the path and
    the tests that assert on its headers still have something to assert about.
    """
    from app.core.ratelimit import limiter

    limiter.forget_all()
    yield
    limiter.forget_all()


@pytest.fixture(autouse=True)
def _process_wide_state_starts_fresh():
    """Caches, breakers and counters do not leak between tests.

    All three are module-level singletons for the life of the process, which
    is right in production and wrong in a suite: a dashboard cached by one
    test is served to the next one, a breaker left open by a failure test
    silently skips the provider call a later test is asserting on, and a
    counter read for an exact value is whatever the file order happened to
    make it. Same failure mode as the auth switches and the rate limiter
    above — a test that breaks somewhere else, later, for no visible reason.
    """
    from app.core import breaker, cache, metrics

    cache.clear_all()
    breaker.reset_all()
    metrics.registry.reset()
    yield
    cache.clear_all()
    breaker.reset_all()


async def _reset_schema() -> None:
    """Give every test an empty schema, without waiting on a lock to clear.

    `DROP TABLE` needs an exclusive lock, and a forecast run does not stop
    being a forecast run because the test that started it has returned: the
    pool finishes fitting, `complete_run` writes its row, the progress relay
    drains. Any of those can still hold SQLite's write lock when the next
    test's reset arrives.

    The lock is not always held briefly, which is what the retry this replaces
    assumed. A connection opened by one of those background tasks belongs to
    that test's event loop, and once the loop is gone the connection can
    neither commit nor roll back — it holds the write lock for the rest of the
    process, and every reset after it fails at the *setup* of some unrelated
    test, which is the least informative place a failure can appear. Waiting
    longer cannot help: a run measured 25 errors against a twenty-second
    deadline and the same 25 against ninety, having spent thirty-five extra
    minutes to reach the identical result.

    So the file is replaced rather than emptied. Unlinking it leaves any
    abandoned writer holding an inode nothing will read again, and the next
    connection opens a new database — which is a reset that cannot block on
    anybody. Postgres has no such orphans, its connections dying with their
    loop, so it keeps the ordinary drop and create.
    """
    await engine.dispose()

    if _SQLITE_DB is None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        return

    # The journal and shared-memory files belong to the database they were
    # opened beside; leaving them behind hands the new file the old one's
    # uncommitted pages.
    for suffix in ("", "-wal", "-shm"):
        _SQLITE_DB.with_name(_SQLITE_DB.name + suffix).unlink(missing_ok=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture(autouse=True)
async def _schema() -> AsyncIterator[None]:
    await _reset_schema()
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
