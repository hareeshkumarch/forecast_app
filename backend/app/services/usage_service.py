from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import utcnow
from app.models.entities import LlmUsageEvent
from app.schemas.usage import (
    LlmUsageBreakdown,
    LlmUsageEventRead,
    LlmUsagePoint,
    LlmUsageResponse,
    LlmUsageTotals,
)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(math.ceil(percentile * len(ordered)) - 1, 0)
    return round(ordered[index], 2)


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


async def summary(session: AsyncSession, *, days: int = 30) -> LlmUsageResponse:
    now = utcnow()
    start = now - timedelta(days=days - 1)
    result = await session.execute(
        select(LlmUsageEvent)
        .where(LlmUsageEvent.created_at >= start)
        .order_by(LlmUsageEvent.created_at.desc())
        .limit(5000)
    )
    events = list(result.scalars().all())

    daily: dict[date, dict[str, float | int]] = defaultdict(
        lambda: {"requests": 0, "successful": 0, "tokens": 0, "cost": 0.0}
    )
    models: dict[tuple[str, str], list[LlmUsageEvent]] = defaultdict(list)

    for event in events:
        day = event.created_at.date()
        daily[day]["requests"] += 1
        daily[day]["successful"] += int(event.status == "success")
        daily[day]["tokens"] += event.total_tokens or 0
        daily[day]["cost"] += event.cost_usd or 0.0
        models[(event.provider, event.model)].append(event)

    latencies = [event.latency_ms for event in events if event.latency_ms is not None]
    totals = LlmUsageTotals(
        requests=len(events),
        successful_requests=sum(event.status == "success" for event in events),
        failed_requests=sum(event.status == "error" for event in events),
        rejected_requests=sum(event.status == "rejected" for event in events),
        input_tokens=sum(event.input_tokens or 0 for event in events),
        output_tokens=sum(event.output_tokens or 0 for event in events),
        cached_input_tokens=sum(event.cached_input_tokens or 0 for event in events),
        reasoning_tokens=sum(event.reasoning_tokens or 0 for event in events),
        total_tokens=sum(event.total_tokens or 0 for event in events),
        cost_usd=round(sum(event.cost_usd or 0.0 for event in events), 8),
        priced_requests=sum(event.cost_usd is not None for event in events),
        average_latency_ms=_average(latencies),
        p95_latency_ms=_percentile(latencies, 0.95),
    )

    timeseries = []
    first_day = start.date()
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        values = daily[day]
        timeseries.append(
            LlmUsagePoint(
                date=day,
                requests=int(values["requests"]),
                successful_requests=int(values["successful"]),
                total_tokens=int(values["tokens"]),
                cost_usd=round(float(values["cost"]), 8),
            )
        )

    by_model = []
    for (provider, model), rows in models.items():
        model_latencies = [row.latency_ms for row in rows if row.latency_ms is not None]
        by_model.append(
            LlmUsageBreakdown(
                provider=provider,
                model=model,
                requests=len(rows),
                successful_requests=sum(row.status == "success" for row in rows),
                total_tokens=sum(row.total_tokens or 0 for row in rows),
                cost_usd=round(sum(row.cost_usd or 0.0 for row in rows), 8),
                priced_requests=sum(row.cost_usd is not None for row in rows),
                average_latency_ms=_average(model_latencies),
            )
        )
    by_model.sort(key=lambda row: (row.cost_usd, row.total_tokens, row.requests), reverse=True)

    return LlmUsageResponse(
        days=days,
        generated_at=now,
        totals=totals,
        timeseries=timeseries,
        by_model=by_model,
        recent=[LlmUsageEventRead.model_validate(event) for event in events[:50]],
    )
