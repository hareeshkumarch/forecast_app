"""The metric set follows the data, and says what it withheld and why."""

from __future__ import annotations

import numpy as np
import pytest

from app.forecasting import metrics
from app.forecasting.diagnostics import profile_series
from app.forecasting.metric_plan import evaluate_plan, plan_for
from app.models.enums import ForecastFrequency

WEEKLY = ForecastFrequency.WEEKLY


def _profile(values: np.ndarray):
    return profile_series(np.asarray(values, dtype=float), WEEKLY)


def _steady(seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 + 10 * np.sin(np.arange(60) / 6) + rng.normal(0, 3, 60)


def _bursty(seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.where(rng.random(60) < 0.7, 0.0, rng.integers(1, 9, 60).astype(float))


def _signed(seed: int = 7) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 20, 60)


class TestWhatTheDataCanCarry:
    def test_a_series_with_zeros_withholds_the_percentage_metrics(self) -> None:
        plan = plan_for(_profile(_bursty()))
        withheld = {item.name for item in plan.withheld}
        assert {"mape", "smape"} <= withheld
        assert "mape" not in plan.reported
        assert "smape" not in plan.reported

    def test_a_series_without_zeros_keeps_them(self) -> None:
        plan = plan_for(_profile(_steady()))
        assert "mape" in plan.reported
        assert "smape" in plan.reported

    def test_a_signed_series_withholds_log_error(self) -> None:
        plan = plan_for(_profile(_signed()))
        assert "rmsle" not in plan.reported
        assert any(item.name == "rmsle" for item in plan.withheld)

    def test_zeros_alone_do_not_withhold_log_error(self) -> None:
        """`log1p` is defined at zero; only a negative breaks it."""
        plan = plan_for(_profile(_bursty()))
        assert "rmsle" in plan.reported

    def test_every_withheld_metric_carries_a_reason(self) -> None:
        for values in (_steady(), _bursty(), _signed()):
            for item in plan_for(_profile(values)).withheld:
                assert item.reason.strip()

    def test_a_withheld_metric_is_never_also_reported(self) -> None:
        for values in (_steady(), _bursty(), _signed()):
            plan = plan_for(_profile(values))
            assert not ({item.name for item in plan.withheld} & set(plan.reported))


class TestWhatLeads:
    def test_bursty_demand_leads_on_a_scaled_metric(self) -> None:
        plan = plan_for(_profile(_bursty()))
        assert plan.headline in {"rmsse", "mase"}

    def test_steady_demand_leads_on_volume_weighted_error(self) -> None:
        assert plan_for(_profile(_steady())).headline == "wmape"

    def test_a_signed_series_is_never_called_bursty(self) -> None:
        """Syntetos-Boylan counts periods with no demand; a signed series has none."""
        plan = plan_for(_profile(_signed()))
        assert "bursts" not in plan.note

    def test_nothing_forbidden_can_reach_a_ranking(self) -> None:
        for values in (_steady(), _bursty(), _signed()):
            plan = plan_for(_profile(values))
            assert not (set(plan.ranking) & metrics.FORBIDDEN_SELECTION_METRICS)

    def test_no_profile_still_yields_a_usable_plan(self) -> None:
        plan = plan_for(None)
        assert plan.headline in plan.reported
        assert plan.ranking


class TestEvaluatingAPlan:
    def test_only_the_planned_metrics_are_computed(self) -> None:
        history = _bursty()
        plan = plan_for(_profile(history))
        scored = evaluate_plan(plan, history[:20], history[:20] * 0.9, insample=history[20:])
        assert set(scored) == set(plan.reported)
        assert "mape" not in scored

    def test_a_withheld_metric_is_not_computed_and_hidden(self) -> None:
        history = _signed()
        plan = plan_for(_profile(history))
        scored = evaluate_plan(plan, history[:20], history[:20], insample=history[20:])
        assert "rmsle" not in scored

    def test_scoring_a_perfect_forecast_gives_no_error(self) -> None:
        history = _steady()
        plan = plan_for(_profile(history))
        scored = evaluate_plan(plan, history[:20], history[:20], insample=history[20:])
        for name in ("mae", "rmse", "medae", "wmape"):
            assert scored[name] == pytest.approx(0.0, abs=1e-9)
