from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.database.base import utcnow
from app.database.session import session_scope
from app.models.entities import ForecastRun, ForecastScenario
from app.models.enums import RunStatus

logger = get_logger(__name__)

TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED)


@dataclass(frozen=True, slots=True)
class Candidate:
    run_id: uuid.UUID
    created_at: str
    status: RunStatus
    age_days: int


@dataclass(frozen=True, slots=True)
class Plan:
    enabled: bool
    keep_runs: int
    older_than_days: int
    removing: tuple[Candidate, ...]
    remaining: int
    protected: dict[str, str]

    @property
    def would_remove(self) -> int:
        return len(self.removing)


async def plan(session: AsyncSession, *, limit: int | None = None) -> Plan:
    batch = limit if limit is not None else settings.retention_batch
    protected: dict[str, str] = {}

    latest = await _latest_completed(session)
    if latest is not None:
        protected[str(latest)] = "the run the dashboard is showing"

    referenced = set(await session.scalars(select(ForecastScenario.run_id).distinct()))
    for run_id in referenced:
        protected.setdefault(str(run_id), "a saved scenario refers to it")

    kept = await _most_recent(session, settings.retention_keep_runs)
    for run_id in kept:
        protected.setdefault(str(run_id), f"among the {settings.retention_keep_runs} most recent")

    cutoff = (
        utcnow() - timedelta(days=settings.retention_run_days)
        if settings.retention_run_days > 0
        else None
    )

    query = select(ForecastRun).where(ForecastRun.status.in_(TERMINAL))
    if cutoff is not None:
        query = query.where(ForecastRun.created_at < cutoff)
    query = query.order_by(ForecastRun.created_at.asc())

    now = utcnow()
    removing: list[Candidate] = []
    remaining = 0
    for run in await session.scalars(query):
        if str(run.id) in protected:
            continue
        if len(removing) >= batch:
            remaining += 1
            continue
        removing.append(
            Candidate(
                run_id=run.id,
                created_at=run.created_at.isoformat(),
                status=run.status,
                age_days=max(0, (now - _aware(run.created_at, now)).days),
            )
        )

    return Plan(
        enabled=settings.retention_enabled,
        keep_runs=settings.retention_keep_runs,
        older_than_days=settings.retention_run_days,
        removing=tuple(removing),
        remaining=remaining,
        protected=protected,
    )


def _aware(value: datetime, reference: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=reference.tzinfo)


async def _latest_completed(session: AsyncSession) -> uuid.UUID | None:
    from app.services import forecast_service

    run = await forecast_service.latest_completed_run(session)
    return run.id if run else None


async def _most_recent(session: AsyncSession, count: int) -> set[uuid.UUID]:
    rows = await session.scalars(
        select(ForecastRun.id).order_by(ForecastRun.created_at.desc()).limit(count)
    )
    return set(rows)


async def sweep(*, force: bool = False) -> Plan:
    from app.services import forecast_service

    if not settings.retention_enabled and not force:
        async with session_scope() as session:
            return await plan(session, limit=0)

    async with session_scope() as session:
        intended = await plan(session)

    removed: list[Candidate] = []
    for candidate in intended.removing:
        try:
            async with session_scope() as session:
                await forecast_service.delete_run(session, candidate.run_id)
            removed.append(candidate)
        except Exception:
            logger.warning("Retention could not remove run %s", candidate.run_id, exc_info=True)

    if removed:
        logger.info(
            "Retention removed %d run(s) older than %d days, keeping the newest %d.",
            len(removed),
            settings.retention_run_days,
            settings.retention_keep_runs,
        )
    return Plan(
        enabled=intended.enabled,
        keep_runs=intended.keep_runs,
        older_than_days=intended.older_than_days,
        removing=tuple(removed),
        remaining=intended.remaining + (len(intended.removing) - len(removed)),
        protected=intended.protected,
    )


async def stored_runs(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(ForecastRun)) or 0)


class Sweeper:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None or not settings.retention_enabled:
            return
        self._task = asyncio.create_task(self._run(), name="retention-sweeper")
        logger.info(
            "Retention is on: runs past %d days are removed hourly, newest %d always kept.",
            settings.retention_run_days,
            settings.retention_keep_runs,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(settings.retention_interval_seconds)
            try:
                await sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("A retention pass failed; will try again", exc_info=True)


sweeper = Sweeper()
