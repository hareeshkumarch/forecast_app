def test_every_offered_provider_has_somewhere_to_send_the_request() -> None:
    """A provider the UI offers and the backend cannot reach is a dead option.

    The two halves live in different languages and different repositories'
    worth of code, so nothing but a test connects them.
    """
    from app.insights.llm import PROVIDER_BASE_URLS

    # These carry their own URL: the reader supplies it.
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
    """build.nvidia.com issues keys for free, which is why it is here.

    The catalogue is browsed at build.nvidia.com but served from
    integrate.api.nvidia.com — pointing at the first gets HTML back.
    """
    from app.insights.llm import PROVIDER_BASE_URLS

    assert PROVIDER_BASE_URLS["nvidia"] == "https://integrate.api.nvidia.com/v1"
