"""What the platform is allowed to forget, and what it never is.

Nothing here runs unless `RETENTION_ENABLED` says so. That default is not
timidity: an issued forecast is a record of what was claimed and when — the
thing `install_append_only_guard` exists to keep honest — and a platform that
prunes it because nobody chose a policy has quietly decided one.

When it is on, three protections hold whatever the limits say. A run that has
not finished is never touched, because deleting a row underneath a running
process is how a forecast fails in a way nobody can explain. The latest
completed run is never touched, because the dashboard reads it and the
alternative is a workspace that empties itself overnight. And a run a saved
scenario points at is never touched, because the scenario is somebody's saved
work and would be left pointing at nothing.

Deletion goes through `forecast_service.delete_run`, which already clears the
points, the series, the exports on disk, the cached aggregates and the
progress state. One deletion path, so a sweeper cannot leave behind the thing
a person deleting by hand would not have.
"""

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
    #: Runs that would go on the next pass, oldest first, capped at the batch.
    removing: tuple[Candidate, ...]
    #: How many more are past the limits and will follow on later passes.
    remaining: int
    #: Named so the answer to "why is that one still here" does not need code.
    protected: dict[str, str]

    @property
    def would_remove(self) -> int:
        return len(self.removing)


async def plan(session: AsyncSession, *, limit: int | None = None) -> Plan:
    """What a pass would do, without doing any of it."""
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
    """A naive timestamp from SQLite compared against an aware one from utcnow."""
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
    """Do one pass. Returns what it removed, in the shape `plan` reports.

    `force` is for the endpoint that asks for it by hand, which is allowed to
    run a pass on a deployment where the periodic sweeper is switched off —
    somebody clicking "free up space" has said what they want more clearly
    than a configuration flag can.
    """
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
            # A run deleted by somebody else between the plan and the pass, or
            # one that started again. Neither is worth stopping the sweep for.
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
    """The periodic pass, on its own task, doing nothing at all when off."""

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
        # Not at boot. A process that has just come up is either being deployed
        # or recovering from something, and neither is the moment to start
        # deleting rows.
        while True:
            await asyncio.sleep(settings.retention_interval_seconds)
            try:
                await sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("A retention pass failed; will try again", exc_info=True)


sweeper = Sweeper()
