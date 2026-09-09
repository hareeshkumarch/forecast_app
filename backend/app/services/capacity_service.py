"""How much of the store this deployment has actually used.

Nothing in the platform ever deleted anything on its own, and the store of
record is a Supabase project with a fixed ceiling. `admission()` caps the
series in one run; nothing caps the sum of every run ever made. A grouped
forecast writes one row per period per series per kind — tens of thousands —
and the tables that hold them have no reason to stop growing.

The failure that produces is the quiet kind: everything works, and then one
insert fails and the run that fails is somebody's. This is the number that
would have said it was coming, and the input to any decision about what to
keep. Read it before setting a retention policy, not after.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.base import Base
from app.database.session import active_target

logger = get_logger(__name__)

#: Long enough that a scrape every fifteen seconds does not walk the catalogue
#: each time, short enough that a person watching a big run land sees it move.
CACHE_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class TableUsage:
    name: str
    rows: int
    #: Bytes on disk including indexes and TOAST, or None where the engine
    #: cannot say — SQLite reports no per-table size.
    bytes: int | None


@dataclass(frozen=True, slots=True)
class Usage:
    tables: tuple[TableUsage, ...]
    total_bytes: int | None
    total_rows: int
    measured_at: float

    def largest(self, count: int = 5) -> tuple[TableUsage, ...]:
        return self.tables[:count]


_cached: Usage | None = None


#: `pg_class.reltuples` is what the planner believes, kept current by autovacuum
#: and free to read. `COUNT(*)` is exact and scans the table — on the one table
#: worth measuring that is the whole point of not doing it.
_POSTGRES = text(
    """
    SELECT c.relname AS name,
           GREATEST(c.reltuples, 0)::bigint AS rows,
           pg_total_relation_size(c.oid) AS bytes
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = current_schema()
      AND c.relkind = 'r'
    ORDER BY pg_total_relation_size(c.oid) DESC
    """
)


async def measure(session: AsyncSession, *, fresh: bool = False) -> Usage:
    global _cached

    if not fresh and _cached is not None and time.monotonic() - _cached.measured_at < CACHE_SECONDS:
        return _cached

    tables = await (_postgres if active_target.url.startswith("postgresql") else _fallback)(session)
    sizes = [table.bytes for table in tables if table.bytes is not None]
    _cached = Usage(
        tables=tuple(tables),
        total_bytes=sum(sizes) if sizes else None,
        total_rows=sum(table.rows for table in tables),
        measured_at=time.monotonic(),
    )
    return _cached


async def _postgres(session: AsyncSession) -> list[TableUsage]:
    result = await session.execute(_POSTGRES)
    return [TableUsage(name=row.name, rows=int(row.rows), bytes=int(row.bytes)) for row in result]


async def _fallback(session: AsyncSession) -> list[TableUsage]:
    """SQLite, and anything else without a catalogue to ask.

    Counted rather than estimated, because there is no estimate to read — and
    the deployments that land here are a laptop and a test suite, where the
    tables are small enough that it does not matter.
    """
    counted: list[TableUsage] = []
    for table in Base.metadata.sorted_tables:
        try:
            rows = await session.scalar(select(func.count()).select_from(table))
        except Exception:
            logger.debug("Could not count %s", table.name, exc_info=True)
            continue
        counted.append(TableUsage(name=table.name, rows=int(rows or 0), bytes=None))
    return sorted(counted, key=lambda item: item.rows, reverse=True)


def forget() -> None:
    global _cached
    _cached = None
