from __future__ import annotations

import json
import uuid

import pytest

from app.core.config import settings
from app.models.enums import RunStatus
from app.services.forecast_service import RunOverrides
from app.services.job_runner import ProgressEvent, executors
from app.services.progress_relay import _decode


def test_run_options_survive_a_round_trip_through_the_row() -> None:
    overrides = RunOverrides(
        max_folds=4,
        metric_weights={"wmape": 0.6, "rmse": 0.4},
        sarimax_order=[1, 1, 1],
        gbm_max_depth=5,
        llm_provider="openai",
        llm_model="gpt-4o-mini",
    )

    restored = RunOverrides.from_stored(overrides.to_stored())

    assert restored.max_folds == 4
    assert restored.metric_weights == {"wmape": 0.6, "rmse": 0.4}
    assert restored.sarimax_order == [1, 1, 1]
    assert restored.gbm_max_depth == 5
    assert restored.llm_provider == "openai"


def test_an_api_key_is_never_stored_in_the_clear() -> None:
    overrides = RunOverrides(llm_api_key="sk-live-do-not-leak", llm_provider="openai")
    stored = overrides.to_stored()

    assert "llm_api_key" not in stored
    assert "sk-live-do-not-leak" not in str(stored)
    assert stored["llm_provider"] == "openai"

    assert RunOverrides.from_stored(stored).llm_api_key == "sk-live-do-not-leak"


def test_unreadable_options_degrade_rather_than_crash() -> None:
    restored = RunOverrides.from_stored({"max_folds": 3, "_secrets": "not-a-valid-token"})

    assert restored.max_folds == 3
    assert restored.llm_api_key is None


def test_empty_options_produce_empty_overrides() -> None:
    assert RunOverrides.from_stored(None).is_empty()
    assert RunOverrides.from_stored({}).is_empty()
    assert RunOverrides().to_stored() == {}


def test_unknown_stored_keys_are_ignored() -> None:
    restored = RunOverrides.from_stored({"max_folds": 2, "from_a_future_version": True})
    assert restored.max_folds == 2


@pytest.mark.parametrize("broker", ["", "redis://localhost:6379/0"])
def test_the_pool_is_skipped_when_a_broker_takes_over(monkeypatch, broker: str) -> None:
    monkeypatch.setattr(settings, "celery_broker_url", broker)

    # A Celery worker is daemonic and cannot spawn a nested pool; with a broker
    # configured the fit has to happen inline instead.
    assert executors.inline is bool(broker)


async def test_a_fit_runs_inline_when_distributed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "celery_broker_url", "redis://localhost:6379/0")

    assert await executors.run(str.upper, "queued") == "QUEUED"


def test_a_progress_frame_survives_the_wire() -> None:
    event = ProgressEvent(
        run_id=uuid.uuid4(),
        status=RunStatus.RUNNING,
        progress=0.3,
        stage="backtesting",
        message="Backtesting candidate models...",
    )

    decoded = _decode(json.dumps(event.to_dict()))

    assert decoded is not None
    assert decoded.run_id == event.run_id
    assert decoded.status is RunStatus.RUNNING
    assert decoded.progress == pytest.approx(0.3)
    assert decoded.stage == "backtesting"


@pytest.mark.parametrize(
    "raw",
    [
        '{"run_id": "not-a-uuid", "status": "running", "progress": 0, "stage": "x"}',
        "{}",
        "nonsense",
    ],
)
def test_a_malformed_progress_frame_is_discarded(raw: str) -> None:
    assert _decode(raw) is None
