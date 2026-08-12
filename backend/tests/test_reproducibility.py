"""A number this product printed must be reproducible on demand.

A customer will challenge a figure, and "that is what the model said in March"
is not an answer. Same inputs, same code, same settings — same number, to the
last decimal. Anything less and the accuracy story cannot be audited, only
believed.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.core.provenance import (
    DECISIVE_SETTINGS,
    FEATURE_VERSION,
    MODEL_VERSION,
    Provenance,
    code_version,
    config_hash,
    current,
)
from app.forecasting.engine import ForecastInput, SeriesInput, run_forecast
from app.models.enums import ForecastFrequency

WEEKLY = ForecastFrequency.WEEKLY


def weeks(count: int, start: date = date(2024, 1, 1)) -> list[date]:
    return [start + timedelta(weeks=index) for index in range(count)]


def series(count: int = 104, seed: int = 20260812) -> list[float]:
    rng = np.random.default_rng(seed)
    index = np.arange(count)
    return list(
        400.0 + 1.5 * index + 60.0 * np.sin(index * 2.0 * np.pi / 52.0) + rng.normal(0, 18, count)
    )


def forecast(values: list[float], periods: list[date], horizon: int = 9):
    return run_forecast(
        ForecastInput(
            series=SeriesInput(periods=periods, values=values),
            frequency=WEEKLY,
            horizon=horizon,
        )
    )


class TestReplayIsExact:
    @pytest.mark.slow
    def test_the_same_inputs_produce_the_same_forecast_to_the_last_decimal(self) -> None:
        periods, values = weeks(104), series()

        first = forecast(values, periods)
        second = forecast(values, periods)

        assert first.selected_model is second.selected_model
        assert first.point_forecast == second.point_forecast
        assert first.lower_bound == second.lower_bound
        assert first.upper_bound == second.upper_bound

    @pytest.mark.slow
    def test_the_candidate_ranking_replays_too(self) -> None:
        periods, values = weeks(104), series()

        first = forecast(values, periods)
        second = forecast(values, periods)

        assert [c["model"] for c in first.candidates] == [c["model"] for c in second.candidates]
        assert [c["rank"] for c in first.candidates] == [c["rank"] for c in second.candidates]
        assert [c["wmape"] for c in first.candidates] == [c["wmape"] for c in second.candidates]

    @pytest.mark.slow
    def test_the_metrics_replay_too(self) -> None:
        periods, values = weeks(104), series()

        first = forecast(values, periods).metrics
        second = forecast(values, periods).metrics

        assert set(first) == set(second)
        for name in first:
            a, b = first[name], second[name]
            if isinstance(a, float) and np.isnan(a):
                assert np.isnan(b), name
            else:
                assert a == b, name

    @pytest.mark.slow
    def test_a_different_history_gives_a_different_answer(self) -> None:
        """The replay assertions must not pass because nothing depends on the data."""
        periods = weeks(104)

        first = forecast(series(seed=1), periods)
        second = forecast(series(seed=2), periods)

        assert first.point_forecast != second.point_forecast


class TestProvenanceIsRecorded:
    def test_a_run_can_name_the_code_and_settings_behind_it(self) -> None:
        stamp = current()

        assert stamp.model_version == MODEL_VERSION
        assert stamp.feature_version == FEATURE_VERSION
        assert stamp.config_hash
        assert stamp.code_version

    def test_the_config_hash_moves_when_a_decisive_setting_moves(self, monkeypatch) -> None:
        from app.core import config as config_module

        before = config_hash()
        monkeypatch.setattr(config_module.settings, "metric_weight_wmape", 0.77, raising=False)
        after = config_hash()

        assert before != after

    def test_the_config_hash_ignores_settings_that_change_no_number(self, monkeypatch) -> None:
        from app.core import config as config_module

        before = config_hash()
        monkeypatch.setattr(config_module.settings, "api_max_page_size", 17, raising=False)

        assert config_hash() == before

    def test_every_decisive_setting_actually_exists(self) -> None:
        from app.core.config import settings

        missing = [name for name in DECISIVE_SETTINGS if not hasattr(settings, name)]

        assert missing == [], f"config_hash covers settings that are gone: {missing}"

    def test_two_stamps_of_the_same_build_agree(self) -> None:
        assert current().matches(current())

    def test_a_different_model_version_will_not_replay(self) -> None:
        now = current()
        older = Provenance(
            code_version=now.code_version,
            model_version="2020.01.1",
            feature_version=now.feature_version,
            config_hash=now.config_hash,
        )

        assert not now.matches(older)

    def test_the_commit_is_resolved_once_and_cached(self) -> None:
        assert code_version() == code_version()
