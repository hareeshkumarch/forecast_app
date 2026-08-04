from __future__ import annotations

import re
from dataclasses import dataclass
from time import perf_counter

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.insights.generators import GeneratedInsight

logger = get_logger(__name__)


@dataclass(slots=True)
class LlmUsageRecord:
    provider: str
    model: str
    status: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    cost_source: str = "unavailable"
    error_code: str | None = None
    insight_type: str | None = None
    applied: bool = False


@dataclass(slots=True)
class LlmCallResult:
    text: str | None
    usage: LlmUsageRecord

NUMBER_PATTERN = re.compile(r"-?\$?\d[\d,]*\.?\d*[%KMB]?")

EMOJI_PATTERN = re.compile(
    r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    r"\U0001F1E0-\U0001F1FF\U00002700-\U000027BF\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF]+"
)

SYSTEM_PROMPT = """You rewrite pre-computed business forecasting insights into professional, clear prose.

Absolute rules:
- Never use any emojis or icon characters.
- Never invent, alter, recompute, round or drop any number, percentage or currency figure.
- Reuse every figure exactly as written in the input.
- Do not add figures that are not in the input.
- Keep the same meaning and direction.
- Title: at most 6 words. Explanation: 2-3 sentences. Action: 1 sentence, imperative.

Reply with exactly three lines, no labels, no markdown, no emojis:
line 1 = title
line 2 = explanation
line 3 = suggested action"""

PROVIDER_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "xai": "https://api.x.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
}


def strip_emojis(text: str) -> str:
    return EMOJI_PATTERN.sub("", text).strip()


def _extract_numbers(text: str) -> set[str]:
    return {match.group().strip().rstrip(".") for match in NUMBER_PATTERN.finditer(text)}


def _numbers_preserved(original: str, rewritten: str) -> bool:
    return _extract_numbers(rewritten) == _extract_numbers(original)


def _resolve_api_key() -> str | None:
    return settings.llm_api_key or settings.anthropic_api_key


def _non_negative_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _non_negative_float(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _usage_record(
    *,
    provider: str,
    model: str,
    payload: dict[str, object],
    latency_ms: float,
    config: dict[str, object],
) -> LlmUsageRecord:
    usage = payload.get("usage")
    raw = usage if isinstance(usage, dict) else {}

    if provider == "anthropic":
        input_tokens = _non_negative_int(raw.get("input_tokens"))
        output_tokens = _non_negative_int(raw.get("output_tokens"))
        cached = sum(
            value or 0
            for value in (
                _non_negative_int(raw.get("cache_read_input_tokens")),
                _non_negative_int(raw.get("cache_creation_input_tokens")),
            )
        )
        cached_input_tokens = cached or None
        reasoning_tokens = None
    else:
        input_tokens = _non_negative_int(raw.get("prompt_tokens"))
        output_tokens = _non_negative_int(raw.get("completion_tokens"))
        prompt_details = raw.get("prompt_tokens_details")
        completion_details = raw.get("completion_tokens_details")
        cached_input_tokens = _non_negative_int(
            prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None
        )
        reasoning_tokens = _non_negative_int(
            completion_details.get("reasoning_tokens")
            if isinstance(completion_details, dict)
            else None
        )

    total_tokens = _non_negative_int(raw.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    provider_cost = _non_negative_float(raw.get("cost"))
    if provider_cost is not None:
        cost_usd = provider_cost
        cost_source = "provider"
    else:
        input_rate = _non_negative_float(config.get("llm_input_cost_per_million"))
        output_rate = _non_negative_float(config.get("llm_output_cost_per_million"))
        if input_tokens is not None and output_tokens is not None and (
            input_rate is not None or output_rate is not None
        ):
            cost_usd = (
                input_tokens * (input_rate or 0.0) + output_tokens * (output_rate or 0.0)
            ) / 1_000_000
            cost_source = "configured"
        else:
            cost_usd = None
            cost_source = "unavailable"

    return LlmUsageRecord(
        provider=provider,
        model=model,
        status="success",
        latency_ms=round(latency_ms, 2),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        cost_source=cost_source,
    )


def _call_llm_api(
    source: str, config: dict[str, object] | None = None
) -> LlmCallResult | None:
    cfg = config or {}
    api_key = str(cfg.get("llm_api_key") or "") if cfg.get("llm_api_key") else _resolve_api_key()
    if not api_key:
        return None

    provider = str(cfg.get("llm_provider") or settings.llm_provider or "openai").lower().strip()
    model = str(
        cfg.get("llm_model")
        or settings.llm_model
        or ("claude-3-5-sonnet-20241022" if provider == "anthropic" else "gpt-4o-mini")
    )
    override_url = str(cfg.get("llm_base_url")) if cfg.get("llm_base_url") else None
    started = perf_counter()

    try:
        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body = {
                "model": model,
                "max_tokens": 400,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": source}],
            }
            with httpx.Client(timeout=10.0) as client:
                res = client.post(url, headers=headers, json=body)
                res.raise_for_status()
                data = res.json()
                content = data.get("content", [])
                text = "".join(
                    b.get("text", "") for b in content if b.get("type") == "text"
                ).strip()
                return LlmCallResult(
                    text=text or None,
                    usage=_usage_record(
                        provider=provider,
                        model=model,
                        payload=data,
                        latency_ms=(perf_counter() - started) * 1000,
                        config=cfg,
                    ),
                )

        base_url = (
            override_url
            or settings.llm_base_url
            or PROVIDER_BASE_URLS.get(provider, "https://api.openai.com/v1")
        ).rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "http://localhost:3000"
            headers["X-Title"] = "Forecasting Platform"

        body = {
            "model": model,
            "max_tokens": 400,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": source},
            ],
        }
        with httpx.Client(timeout=10.0) as client:
            res = client.post(url, headers=headers, json=body)
            res.raise_for_status()
            data = res.json()
            choices = data.get("choices", [])
            if choices:
                text = str(choices[0].get("message", {}).get("content", "")).strip()
                return LlmCallResult(
                    text=text or None,
                    usage=_usage_record(
                        provider=provider,
                        model=model,
                        payload=data,
                        latency_ms=(perf_counter() - started) * 1000,
                        config=cfg,
                    ),
                )

    except Exception as exc:
        logger.warning("LLM API call failed for provider %s: %s", provider, exc)
        status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        return LlmCallResult(
            text=None,
            usage=LlmUsageRecord(
                provider=provider,
                model=model,
                status="error",
                latency_ms=round((perf_counter() - started) * 1000, 2),
                error_code=str(status_code) if status_code is not None else type(exc).__name__,
            ),
        )

    return LlmCallResult(
        text=None,
        usage=LlmUsageRecord(
            provider=provider,
            model=model,
            status="rejected",
            latency_ms=round((perf_counter() - started) * 1000, 2),
            error_code="empty_response",
        ),
    )


def rewrite_insights(
    insights: list[GeneratedInsight],
    llm_config: dict[str, object] | None = None,
    usage_sink: list[LlmUsageRecord] | None = None,
) -> list[GeneratedInsight]:
    for insight in insights:
        insight.title = strip_emojis(insight.title)
        insight.explanation = strip_emojis(insight.explanation)
        insight.suggested_action = strip_emojis(insight.suggested_action)

    if not llm_enabled(llm_config) or not insights:
        return insights

    for insight in insights:
        source = f"{insight.title}\n{insight.explanation}\n{insight.suggested_action}"
        result = _call_llm_api(source, config=llm_config)
        if result is None:
            continue
        usage = result.usage
        usage.insight_type = insight.type.value
        if usage_sink is not None:
            usage_sink.append(usage)
        text = result.text
        if not text:
            if usage.status == "success":
                usage.status = "rejected"
                usage.error_code = "empty_response"
            continue

        text = strip_emojis(text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 3:
            usage.status = "rejected"
            usage.error_code = "invalid_format"
            continue

        title, explanation, action = lines[0], lines[1], " ".join(lines[2:])

        if not _numbers_preserved(source, f"{title}\n{explanation}\n{action}"):
            logger.warning(
                "LLM rewrite for %s introduced a number not present in the computed insight; discarding.",
                insight.type,
            )
            usage.status = "rejected"
            usage.error_code = "number_validation"
            continue

        insight.title = strip_emojis(title[:160])
        insight.explanation = strip_emojis(explanation)
        insight.suggested_action = strip_emojis(action)
        usage.applied = True

    return insights


def llm_enabled(llm_config: dict[str, object] | None = None) -> bool:
    if llm_config and llm_config.get("llm_api_key"):
        return True
    return bool(_resolve_api_key())
