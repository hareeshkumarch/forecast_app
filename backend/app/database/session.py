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

active_target = resolve_target()

_backend = make_url(active_target.url).get_backend_name()

if _backend == "sqlite":
    _pool_options: dict[str, object] = {}
elif active_target.pooled:
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

install_append_only_guard()


_TIMEOUTS_APPLY = _backend == "postgresql"


async def _limit(session: AsyncSession, seconds: float) -> None:
    if not _TIMEOUTS_APPLY or seconds <= 0:
        return
    await session.execute(text(f"SET LOCAL statement_timeout = {int(seconds * 1000)}"))


async def get_session() -> AsyncIterator[AsyncSession]:
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
    async with SessionFactory() as session:
        try:
            await _limit(session, settings.db_write_timeout_seconds)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
