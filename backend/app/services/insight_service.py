from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import utcnow
from app.insights import llm as llm_api
from app.insights.generators import GeneratedInsight
from app.insights.llm import LlmProbe, LlmUsageRecord
from app.models.entities import Insight, LlmUsageEvent
from app.models.enums import InsightSeverity, InsightType

REFUSAL_REASONS = {
    "no_key": "no API key was configured",
    "401": "the provider rejected the API key",
    "403": "the key is not allowed to use this model",
    "404": "the provider does not recognise that model",
    "429": "the provider is rate-limiting this key",
    "empty_response": "the model returned nothing",
    "invalid_format": "the model did not answer in the expected shape",
    "number_validation": "the model changed a figure, so its wording was discarded",
}


@dataclass(slots=True)
class RewriteOutcome:
    considered: int
    rewritten: int
    provider: str
    model: str
    reasons: dict[str, int] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        if self.considered == 0:
            return "There are no insights to rewrite yet."
        if self.rewritten == self.considered:
            return f"All {self.considered} insights rewritten by {self.model}."
        if self.rewritten == 0:
            reason = next(iter(self.reasons), None)
            detail = f" — {reason}" if reason else ""
            return f"None of the {self.considered} insights could be rewritten{detail}."
        reason = next(iter(self.reasons), None)
        detail = f"; the rest kept the platform's wording because {reason}" if reason else ""
        return f"{self.rewritten} of {self.considered} insights rewritten by {self.model}{detail}."


def _as_generated(row: Insight) -> GeneratedInsight:
    return GeneratedInsight(
        type=InsightType(row.type),
        severity=InsightSeverity(row.severity),
        title=row.source_title,
        explanation=row.source_explanation,
        suggested_action=row.source_action,
        metric_name=row.metric_name,
        metric_value=row.metric_value,
        metric_unit=row.metric_unit,
        supporting_data=dict(row.supporting_data or {}),
        generated_at=row.generated_at,
    )


async def _stored(session: AsyncSession, run_id: uuid.UUID) -> list[Insight]:
    result = await session.execute(
        select(Insight).where(Insight.run_id == run_id).order_by(Insight.rank)
    )
    return list(result.scalars().all())


def _reasons(records: list[LlmUsageRecord]) -> dict[str, int]:
    counts = Counter(
        REFUSAL_REASONS.get(record.error_code or "", "the provider could not be reached")
        for record in records
        if not record.applied
    )
    return dict(counts.most_common())


async def rewrite(
    session: AsyncSession, run_id: uuid.UUID, llm_config: dict[str, object] | None
) -> RewriteOutcome:
    provider = llm_api.resolve_provider(llm_config)
    model = llm_api.resolve_model(llm_config)

    rows = await _stored(session, run_id)
    if not rows:
        return RewriteOutcome(considered=0, rewritten=0, provider=provider, model=model)

    drafts = [_as_generated(row) for row in rows]
    usage: list[LlmUsageRecord] = []

    await asyncio.to_thread(llm_api.rewrite_insights, drafts, llm_config, usage)

    applied = {record.insight_type for record in usage if record.applied}
    rewritten = 0

    for row, draft in zip(rows, drafts, strict=True):
        was_applied = row.type.value in applied
        row.title = draft.title
        row.explanation = draft.explanation
        row.suggested_action = draft.suggested_action
        row.llm_rewritten = was_applied
        rewritten += int(was_applied)

    record_usage(session, run_id, usage)
    await session.flush()

    return RewriteOutcome(
        considered=len(rows),
        rewritten=rewritten,
        provider=provider,
        model=model,
        reasons=_reasons(usage),
    )


async def reset(session: AsyncSession, run_id: uuid.UUID) -> int:
    rows = await _stored(session, run_id)
    for row in rows:
        row.title = row.source_title
        row.explanation = row.source_explanation
        row.suggested_action = row.source_action
        row.llm_rewritten = False

    await session.flush()
    return len(rows)


async def check(llm_config: dict[str, object] | None) -> LlmProbe:
    return await asyncio.to_thread(llm_api.probe, llm_config)


def record_usage(session: AsyncSession, run_id: uuid.UUID, usage: list[LlmUsageRecord]) -> None:
    now = utcnow()
    for record in usage:
        session.add(
            LlmUsageEvent(
                run_id=run_id,
                purpose="insight_rewrite",
                insight_type=record.insight_type,
                provider=record.provider,
                model=record.model,
                status=record.status,
                applied=record.applied,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                cached_input_tokens=record.cached_input_tokens,
                reasoning_tokens=record.reasoning_tokens,
                total_tokens=record.total_tokens,
                latency_ms=record.latency_ms,
                cost_usd=record.cost_usd,
                cost_source=record.cost_source,
                error_code=record.error_code,
                created_at=now,
            )
        )
