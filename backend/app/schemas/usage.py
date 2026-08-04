from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class LlmUsageTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: int
    successful_requests: int
    failed_requests: int
    rejected_requests: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    total_tokens: int
    cost_usd: float
    priced_requests: int
    average_latency_ms: float | None
    p95_latency_ms: float | None


class LlmUsagePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    requests: int
    successful_requests: int
    total_tokens: int
    cost_usd: float


class LlmUsageBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    requests: int
    successful_requests: int
    total_tokens: int
    cost_usd: float
    priced_requests: int
    average_latency_ms: float | None


class LlmUsageEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    run_id: uuid.UUID | None
    purpose: str
    insight_type: str | None
    provider: str
    model: str
    status: str
    applied: bool
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    latency_ms: float | None
    cost_usd: float | None
    cost_source: str
    error_code: str | None
    created_at: datetime


class LlmUsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int
    generated_at: datetime
    totals: LlmUsageTotals
    timeseries: list[LlmUsagePoint]
    by_model: list[LlmUsageBreakdown]
    recent: list[LlmUsageEventRead]
