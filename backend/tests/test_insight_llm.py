def test_every_offered_provider_has_somewhere_to_send_the_request() -> None:
    from app.insights.llm import PROVIDER_BASE_URLS

    supplies_own_url = {"custom", "anthropic"}
    offered = {
        "openai",
        "anthropic",
        "gemini",
        "xai",
        "groq",
        "openrouter",
        "nvidia",
        "custom",
    }

    for provider in offered - supplies_own_url:
        assert provider in PROVIDER_BASE_URLS, f"{provider} is offered but has no base URL"


def test_nvidia_points_at_the_openai_shaped_endpoint() -> None:
    from app.insights.llm import PROVIDER_BASE_URLS

    assert PROVIDER_BASE_URLS["nvidia"] == "https://integrate.api.nvidia.com/v1"
