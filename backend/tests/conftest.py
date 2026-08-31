from __future__ import annotations

import asyncio
import os
import tempfile
import time
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
from sqlalchemy.exc import OperationalError  # noqa: E402
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


#: How long the schema reset will wait for a lingering writer before giving up.
#: Generous because the thing it waits for is a forecast finishing, and mean:
#: the failure it replaces is an ERROR at setup of an unrelated test.
_SCHEMA_LOCK_TIMEOUT_SECONDS = 20.0


async def _reset_schema() -> None:
    """Drop and recreate every table, waiting out a writer that has not left.

    `DROP TABLE` needs an exclusive lock, and a forecast run does not stop
    being a forecast run because the test that started it has returned: the
    pool finishes fitting, `complete_run` writes its row, the progress relay
    drains. Any of those can still hold SQLite's write lock when the next
    test's reset arrives, and the reset then fails with "database is locked"
    at the *setup* of some unrelated test, which is the least informative
    place a failure can appear.

    Retrying rather than serialising the suite: this is a real race with a
    short tail, and the alternative — `-n0` — trades four minutes for
    twenty-two. Retrying rather than a `busy_timeout` pragma because the lock
    is taken and released repeatedly by the background work rather than held
    once, so waiting inside one statement does not help.
    """
    deadline = time.monotonic() + _SCHEMA_LOCK_TIMEOUT_SECONDS
    delay = 0.05
    while True:
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
                await connection.run_sync(Base.metadata.create_all)
            return
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, 1.0)


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
