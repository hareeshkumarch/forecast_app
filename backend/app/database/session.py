from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.database.target import connect_args, resolve_target
from app.models.append_only import install as install_append_only_guard

# Supabase when it is configured and reachable, the local PostgreSQL otherwise.
# Resolved once per process: a request must not discover halfway through that it
# is talking to a different store than the one it read from.
active_target = resolve_target()

_backend = make_url(active_target.url).get_backend_name()

if _backend == "sqlite":
    _pool_options: dict[str, object] = {}
elif active_target.pooled:
    # Supabase's pooler does its own pooling; a second pool in front of it only
    # holds connections the project's quota could be spending elsewhere.
    _pool_options = {"poolclass": NullPool}
else:
    _pool_options = {"pool_size": 10, "max_overflow": 5}

engine = create_async_engine(
    active_target.url,
    echo=False,
    pool_pre_ping=True,
    connect_args=connect_args(active_target),
    **_pool_options,
)


SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Issued forecasts are a record of what was claimed and when. Nothing that goes
# through this factory can rewrite one; a re-run has to make a new run_id.
install_append_only_guard()


#: Only PostgreSQL has a statement timeout worth setting. SQLite is the test
#: and local store and takes a lock rather than a deadline.
_TIMEOUTS_APPLY = _backend == "postgresql"


async def _limit(session: AsyncSession, seconds: float) -> None:
    """Bound how long any one statement in this transaction may run.

    `SET LOCAL` rather than a connection-level setting on purpose: it is scoped
    to the transaction and reset at commit, which is the only form that
    survives pgbouncer in transaction mode — where the server connection under
    this session belongs to somebody else the moment it ends.

    Without a bound, a query has nothing at all to stop it. The concurrency
    ceiling sheds requests that have not started; it cannot touch one already
    running, and there are ten pooled connections for a runaway aggregate to
    sit on.
    """
    if not _TIMEOUTS_APPLY or seconds <= 0:
        return
    await session.execute(text(f"SET LOCAL statement_timeout = {int(seconds * 1000)}"))


async def get_session() -> AsyncIterator[AsyncSession]:
    """A session for one HTTP request. Reads, and the writes a request makes."""
    async with SessionFactory() as session:
        try:
            await _limit(session, settings.db_statement_timeout_seconds)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A session outside a request — a forecast persisting what it produced.

    Takes the longer budget. A grouped run writes one row per period per series
    per kind, tens of thousands of them, and that is slow rather than stuck:
    holding it to the read timeout would abort exactly the runs worth keeping.
    """
    async with SessionFactory() as session:
        try:
            await _limit(session, settings.db_write_timeout_seconds)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
