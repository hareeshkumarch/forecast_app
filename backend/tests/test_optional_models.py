from __future__ import annotations

import importlib.machinery
import sys
import types
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.forecasting import availability
from app.forecasting.availability import ModelAvailability
from app.forecasting.models import ProphetForecaster, build_candidates, unavailable_models
from app.models.enums import ForecastFrequency, ModelKind

MONTHLY = ForecastFrequency.MONTHLY

OPERATOR_WORDS = (
    "pip",
    "requirements",
    "docker",
    "build-arg",
    "rebuild",
    "cmdstanpy",
    "makefile",
)


@pytest.fixture(autouse=True)
def _clear_probe_caches() -> Iterator[None]:
    availability.prophet_availability.cache_clear()
    availability._optional_model_status.cache_clear()
    yield
    availability.prophet_availability.cache_clear()
    availability._optional_model_status.cache_clear()


def _fake_prophet(exc: Exception | None) -> types.ModuleType:
    module = types.ModuleType("prophet")
    module.__spec__ = importlib.machinery.ModuleSpec("prophet", None)

    class _Prophet:
        def __init__(self, **_: object) -> None:
            if exc is not None:
                raise exc

    module.Prophet = _Prophet  # type: ignore[attr-defined]
    return module


def _install_fake(monkeypatch: pytest.MonkeyPatch, exc: Exception | None) -> None:
    monkeypatch.setitem(sys.modules, "prophet", _fake_prophet(exc))
    monkeypatch.delitem(sys.modules, "prophet.models", raising=False)
    availability.prophet_availability.cache_clear()


def _absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "prophet", raising=False)
    monkeypatch.setattr(
        availability,
        "prophet_availability",
        lambda: availability._NOT_INSTALLED,
    )


def test_a_prophet_that_imports_but_cannot_start_is_not_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(
        monkeypatch,
        AttributeError("'Prophet' object has no attribute 'stan_backend'"),
    )

    status = availability.prophet_availability()

    assert status.available is False
    assert "could not start" in status.reason
    assert "stan_backend" in status.operator_hint

    monkeypatch.setattr(availability, "prophet_availability", lambda: status)
    assert ProphetForecaster.available() is False


def test_a_working_prophet_is_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, None)

    status = availability.prophet_availability()

    assert status.available is True
    assert status.reason is None
    assert unavailable_models() == {}


def test_an_absent_prophet_reads_differently_from_a_broken_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch, RuntimeError("no backend"))
    broken = availability.prophet_availability()

    assert broken.reason != availability._NOT_INSTALLED.reason
    assert broken.operator_hint != availability._NOT_INSTALLED.operator_hint
    assert "not installed" in availability._NOT_INSTALLED.reason


@pytest.mark.parametrize(
    "status",
    [availability._NOT_INSTALLED, availability._broken("ValueError: missing makefile")],
    ids=["absent", "broken"],
)
def test_the_user_facing_reason_never_carries_operator_instructions(
    status: ModelAvailability,
) -> None:
    assert status.reason is not None
    lowered = status.reason.lower()
    for word in OPERATOR_WORDS:
        assert word not in lowered, f"{word!r} leaked into user-facing copy: {status.reason}"

    assert "prophet" in lowered
    assert "models tried" in lowered


def test_the_operator_hint_says_how_to_fix_it() -> None:
    assert "requirements-optional.txt" in availability._NOT_INSTALLED.operator_hint
    assert "INSTALL_OPTIONAL_MODELS" in availability._NOT_INSTALLED.operator_hint
    assert "cmdstanpy" in availability._broken("boom").operator_hint


def test_unavailable_models_returns_records_not_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _absent(monkeypatch)

    missing = unavailable_models()

    assert set(missing) == {ModelKind.PROPHET}
    assert isinstance(missing[ModelKind.PROPHET], ModelAvailability)
    assert missing[ModelKind.PROPHET].operator_hint


def test_prophet_is_left_out_of_the_roster_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _absent(monkeypatch)

    kinds = {candidate.kind for candidate in build_candidates(MONTHLY)}

    assert ModelKind.PROPHET not in kinds
    assert {ModelKind.NAIVE, ModelKind.THETA, ModelKind.SARIMAX} <= kinds


def test_choosing_only_an_unavailable_model_blames_the_server_not_the_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _absent(monkeypatch)

    with pytest.raises(ValueError) as caught:
        build_candidates(MONTHLY, {"candidate_models": ["prophet"]})

    message = str(caught.value)
    assert "Prophet is not available on this server" in message
    assert "Choose another model" in message
    assert "Holt-Winters" in message
    assert "holt_winters" not in message


def test_choosing_a_model_that_does_not_suit_the_series_says_so_instead() -> None:
    with pytest.raises(ValueError) as caught:
        build_candidates(MONTHLY, {"candidate_models": ["nonsense_model"]})

    message = str(caught.value)
    assert "not available on this server" not in message
    assert "suit this series" in message


def test_an_unavailable_model_is_reported_as_a_failed_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _absent(monkeypatch)

    missing = unavailable_models()

    assert ModelKind.PROPHET in missing
    assert missing[ModelKind.PROPHET].reason
    assert "requirements" not in missing[ModelKind.PROPHET].reason.lower()


async def test_capabilities_lists_every_model_kind(client: AsyncClient) -> None:
    response = await client.get("/api/health/capabilities")

    assert response.status_code == 200, response.text
    body = response.json()
    assert {row["model"] for row in body["models"]} == {kind.value for kind in ModelKind}
    assert all(row["label"] for row in body["models"])


async def test_capabilities_never_ships_the_operator_hint(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        availability,
        "optional_model_status",
        lambda: (availability._broken("ValueError: /usr/local/lib/python3.12/..."),),
    )

    response = await client.get("/api/health/capabilities")

    assert response.status_code == 200, response.text
    raw = response.text
    assert "operator_hint" not in raw
    assert "/usr/local/lib" not in raw
    assert "cmdstanpy" not in raw

    prophet = next(r for r in response.json()["models"] if r["model"] == "prophet")
    assert prophet["available"] is False
    assert prophet["reason"]


async def test_capabilities_marks_the_always_present_models_available(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        availability, "optional_model_status", lambda: (availability._NOT_INSTALLED,)
    )

    body = (await client.get("/api/health/capabilities")).json()
    rows = {row["model"]: row for row in body["models"]}

    assert body["unavailable_models"] == ["prophet"]
    assert rows["prophet"]["available"] is False
    assert rows["sarimax"]["available"] is True
    assert rows["gradient_boosting"]["available"] is True


async def test_health_reports_which_models_are_missing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        availability, "optional_model_status", lambda: (availability._NOT_INSTALLED,)
    )

    body = (await client.get("/api/health")).json()

    assert body["unavailable_models"] == ["prophet"]
    assert body["status"] == "ok"
