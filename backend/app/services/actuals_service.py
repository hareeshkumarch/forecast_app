from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ActualObservation

TOTAL_KEY = ""


def series_key(key: Mapping[str, object] | None) -> str:
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
    query = select(ActualObservation).where(ActualObservation.dataset_id == dataset_id)
    if as_of is not None:
        query = query.where(ActualObservation.revised_at <= as_of)

    rows = (await session.execute(query.order_by(ActualObservation.revised_at))).scalars().all()

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
    resolved = series_key(key)
    return [
        Reading(series_key=resolved, target_date=period, value=float(value))
        for period, value in sorted(totals.items())
    ]
