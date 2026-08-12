"""Recording what actually happened, without losing what we used to think.

Actuals get restated. A late invoice lands, a return is processed, a
warehouse corrects a count, and the number for a week that closed a month ago
changes. If the restatement overwrites the old reading then every accuracy
figure computed before it silently changes too, and a forecast that was scored
against 1,200 units last month is now scored against 1,340 — the model looks
worse, nobody changed it, and there is no record of why.

So a reading is appended, never replaced, and every query names the moment it
is asking about.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ActualObservation

#: The whole-business total, which has no dimensions to key on.
TOTAL_KEY = ""


def series_key(key: Mapping[str, object] | None) -> str:
    """A stable string for a grain, so the same series keys the same way twice.

    Sorted and JSON-encoded rather than str()-ed: dictionary order is insertion
    order in Python, and two runs that built the same grain in a different
    column order would otherwise write to two different series.
    """
    if not key:
        return TOTAL_KEY
    return json.dumps({str(k): str(v) for k, v in sorted(key.items())}, separators=(",", ":"))


@dataclass(slots=True, frozen=True)
class Reading:
    series_key: str
    target_date: date
    value: float


async def record(
    session: AsyncSession,
    dataset_id: UUID,
    readings: Iterable[Reading],
    *,
    revised_at: datetime | None = None,
    source_dataset_id: UUID | None = None,
) -> int:
    """Append a batch of readings. Returns how many rows were written.

    A reading identical to the newest one already held is not written again:
    re-uploading the same file should not manufacture a revision history that
    says the number changed when it did not.
    """
    stamp = revised_at or datetime.now(UTC)
    batch = list(readings)
    if not batch:
        return 0

    latest = await current(session, dataset_id, as_of=stamp)

    rows = [
        ActualObservation(
            dataset_id=dataset_id,
            series_key=reading.series_key,
            target_date=reading.target_date,
            value=float(reading.value),
            revised_at=stamp,
            source_dataset_id=source_dataset_id,
        )
        for reading in batch
        if latest.get((reading.series_key, reading.target_date)) != float(reading.value)
    ]

    session.add_all(rows)
    await session.flush()
    return len(rows)


async def current(
    session: AsyncSession,
    dataset_id: UUID,
    *,
    as_of: datetime | None = None,
) -> dict[tuple[str, date], float]:
    """The reading in force for each period, as it stood at `as_of`.

    Leaving `as_of` unset asks for what is believed now. Passing the moment a
    run was scored replays exactly what that run was scored against, which is
    the whole reason the older readings are kept.
    """
    query = select(ActualObservation).where(ActualObservation.dataset_id == dataset_id)
    if as_of is not None:
        query = query.where(ActualObservation.revised_at <= as_of)

    rows = (await session.execute(query.order_by(ActualObservation.revised_at))).scalars().all()

    # Ordered oldest first, so the last write for a key is the one in force.
    in_force: dict[tuple[str, date], float] = {}
    for row in rows:
        in_force[(row.series_key, row.target_date)] = row.value
    return in_force


async def revisions(
    session: AsyncSession,
    dataset_id: UUID,
    key: str,
    target_date: date,
) -> list[ActualObservation]:
    """Every reading ever recorded for one period, oldest first."""
    query = (
        select(ActualObservation)
        .where(
            ActualObservation.dataset_id == dataset_id,
            ActualObservation.series_key == key,
            ActualObservation.target_date == target_date,
        )
        .order_by(ActualObservation.revised_at)
    )
    return list((await session.execute(query)).scalars().all())


async def restated_since(
    session: AsyncSession,
    dataset_id: UUID,
    since: datetime,
) -> list[tuple[str, date]]:
    """Which periods have been restated since a moment — the runs worth rescoring."""
    query = select(ActualObservation).where(
        ActualObservation.dataset_id == dataset_id,
        ActualObservation.revised_at > since,
    )
    rows = (await session.execute(query)).scalars().all()
    return sorted({(row.series_key, row.target_date) for row in rows})


def readings_from(
    totals: Mapping[date, float],
    key: Mapping[str, object] | None = None,
) -> Sequence[Reading]:
    """Turn a period-to-value mapping into readings for one series."""
    resolved = series_key(key)
    return [
        Reading(series_key=resolved, target_date=period, value=float(value))
        for period, value in sorted(totals.items())
    ]
