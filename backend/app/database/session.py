from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database.target import connect_args, resolve_target

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


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
