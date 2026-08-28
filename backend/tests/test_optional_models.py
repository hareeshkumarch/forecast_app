"""What happens on a deployment that is missing an optional forecaster.

Prophet is the only one, and for most of this file's life it will be present
(the image installs it), so the tests that matter here fake its absence rather
than skipping. A deployment without Prophet is a supported configuration and
the copy it produces is a product surface — it should not rot just because
the machine running the suite happens to be complete.
"""

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

#: Words that belong in a log line or a runbook and never in the dashboard.
#: "installed" is not among them — "Prophet is not installed" is a plain
#: statement of what happened, and the thing to keep out is the shell command.
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
    """The probes are `@cache`d for the process; tests must not inherit each
    other's answers, nor leave a faked one behind for the rest of the suite."""
    availability.prophet_availability.cache_clear()
    availability._optional_model_status.cache_clear()
    yield
    availability.prophet_availability.cache_clear()
    availability._optional_model_status.cache_clear()


def _fake_prophet(exc: Exception | None) -> types.ModuleType:
    """A module named `prophet` that imports cleanly and may fail to build.

    This is the shape of the real failure: the package is on the path, so
    `find_spec` finds it and an import check passes, and the Stan backend only
    refuses when a model is constructed.
    """
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
    # `_stan_backend_detail` reaches for this to explain itself; without it the
    # probe falls back to the exception, which is the path worth testing.
    monkeypatch.delitem(sys.modules, "prophet.models", raising=False)
    availability.prophet_availability.cache_clear()


def _absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "prophet", raising=False)
    monkeypatch.setattr(
        availability,
        "prophet_availability",
        lambda: availability._NOT_INSTALLED,
    )


# --------------------------------------------------------------------------
# The probe


def test_a_prophet_that_imports_but_cannot_start_is_not_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this module was written for.

    cmdstanpy 1.3.0 rejects the CmdStan tree Prophet's wheel ships, and the
    result is not an ImportError — `import prophet` succeeds and every fit
    raises. An availability check built on `find_spec` calls that installation
    healthy, puts Prophet on the roster, and hands the user a run with one
    candidate that lost to an exception.
    """
    _install_fake(
        monkeypatch,
        AttributeError("'Prophet' object has no attribute 'stan_backend'"),
    )

    status = availability.prophet_availability()

    assert status.available is False
    assert "could not start" in status.reason
    # The reason a person can act on survives into the hint.
    assert "stan_backend" in status.operator_hint

    # And the roster agrees, which is the part that keeps it out of the run.
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
    """Two states, two messages. 'Not installed' points at the image;
    'installed but will not start' points at the pins. Collapsing them sends
    whoever is holding the pager to the wrong place."""
    _install_fake(monkeypatch, RuntimeError("no backend"))
    broken = availability.prophet_availability()

    assert broken.reason != availability._NOT_INSTALLED.reason
    assert broken.operator_hint != availability._NOT_INSTALLED.operator_hint
    assert "not installed" in availability._NOT_INSTALLED.reason


# --------------------------------------------------------------------------
# Who reads which half


@pytest.mark.parametrize(
    "status",
    [availability._NOT_INSTALLED, availability._broken("ValueError: missing makefile")],
    ids=["absent", "broken"],
)
def test_the_user_facing_reason_never_carries_operator_instructions(
    status: ModelAvailability,
) -> None:
    """`pip install -r requirements-optional.txt` used to be rendered in the
    model comparison table, to people who have no shell on the box and no
    reason to want one."""
    assert status.reason is not None
    lowered = status.reason.lower()
    for word in OPERATOR_WORDS:
        assert word not in lowered, f"{word!r} leaked into user-facing copy: {status.reason}"

    # It still has to say what happened to their forecast.
    assert "prophet" in lowered
    assert "models tried" in lowered


def test_the_operator_hint_says_how_to_fix_it() -> None:
    """The other half of the split: the detail has to survive somewhere."""
    assert "requirements-optional.txt" in availability._NOT_INSTALLED.operator_hint
    assert "INSTALL_OPTIONAL_MODELS" in availability._NOT_INSTALLED.operator_hint
    assert "cmdstanpy" in availability._broken("boom").operator_hint


def test_unavailable_models_returns_records_not_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flattening to a string is what merged the two audiences in the first
    place, so the type is the guard."""
    _absent(monkeypatch)

    missing = unavailable_models()

    assert set(missing) == {ModelKind.PROPHET}
    assert isinstance(missing[ModelKind.PROPHET], ModelAvailability)
    assert missing[ModelKind.PROPHET].operator_hint


# --------------------------------------------------------------------------
# The run


def test_prophet_is_left_out_of_the_roster_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _absent(monkeypatch)

    kinds = {candidate.kind for candidate in build_candidates(MONTHLY)}

    assert ModelKind.PROPHET not in kinds
    # Losing an optional model must not thin out the rest.
    assert {ModelKind.NAIVE, ModelKind.THETA, ModelKind.SARIMAX} <= kinds


def test_choosing_only_an_unavailable_model_blames_the_server_not_the_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old message listed raw enum values and said the models did not suit
    the series, which is false and unactionable — nothing about the user's
    data is the problem."""
    _absent(monkeypatch)

    with pytest.raises(ValueError) as caught:
        build_candidates(MONTHLY, {"candidate_models": ["prophet"]})

    message = str(caught.value)
    assert "Prophet is not available on this server" in message
    # Names a way out, in the labels the picker uses.
    assert "Choose another model" in message
    assert "Holt-Winters" in message
    assert "holt_winters" not in message


def test_choosing_a_model_that_does_not_suit_the_series_says_so_instead() -> None:
    """The other branch of the same error, which must not blame the server."""
    with pytest.raises(ValueError) as caught:
        build_candidates(MONTHLY, {"candidate_models": ["nonsense_model"]})

    message = str(caught.value)
    assert "not available on this server" not in message
    assert "suit this series" in message


def test_an_unavailable_model_is_reported_as_a_failed_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reported, not hidden: a user comparing models should see that Prophet
    was not among them, and why."""
    _absent(monkeypatch)

    missing = unavailable_models()

    assert ModelKind.PROPHET in missing
    assert missing[ModelKind.PROPHET].reason
    assert "requirements" not in missing[ModelKind.PROPHET].reason.lower()


# --------------------------------------------------------------------------
# The API the picker is built from


async def test_capabilities_lists_every_model_kind(client: AsyncClient) -> None:
    response = await client.get("/api/health/capabilities")

    assert response.status_code == 200, response.text
    body = response.json()
    assert {row["model"] for row in body["models"]} == {kind.value for kind in ModelKind}
    assert all(row["label"] for row in body["models"])


async def test_capabilities_never_ships_the_operator_hint(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hint quotes exception text and absolute paths from inside the
    container, and this endpoint is served to any browser that reaches the
    distribution."""
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
    # statsmodels and scikit-learn are hard requirements, so these cannot be
    # missing and must never be greyed out in the picker.
    assert rows["sarimax"]["available"] is True
    assert rows["gradient_boosting"]["available"] is True


async def test_health_reports_which_models_are_missing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So that one `curl /api/health` answers 'is Prophet live on this box?'
    without a shell on the instance."""
    monkeypatch.setattr(
        availability, "optional_model_status", lambda: (availability._NOT_INSTALLED,)
    )

    body = (await client.get("/api/health")).json()

    assert body["unavailable_models"] == ["prophet"]
    # An optional model is optional: its absence is not a degraded service.
    assert body["status"] == "ok"
