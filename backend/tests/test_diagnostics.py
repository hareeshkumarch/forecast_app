from __future__ import annotations

from datetime import date

import numpy as np

from app.forecasting.backtest import BacktestResult, FoldResult, _diverged, plan_backtest
from app.forecasting.diagnostics import minimum_history, profile_series
from app.forecasting.engine import ForecastInput, SeriesInput, run_forecast
from app.forecasting.frequency import add_periods
from app.forecasting.models import build_candidates
from app.forecasting.selection import metric_weights_for, penalty_scale, select_model
from app.forecasting.transforms import build_transform
from app.models.enums import ForecastFrequency, ModelKind

MONTHLY = ForecastFrequency.MONTHLY
WEEKLY = ForecastFrequency.WEEKLY
DAILY = ForecastFrequency.DAILY


def seasonal_series(n: int, period: int, *, amplitude: float = 4_000.0, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return 20_000 + 150 * t + amplitude * np.sin(2 * np.pi * t / period) + rng.normal(0, 200, n)


def test_seasonal_period_is_detected_not_assumed() -> None:
    weekly = profile_series(seasonal_series(104, 13), WEEKLY)
    assert weekly.seasonal_period == 13, "a 13-week cycle must not be read as the default 52"
    assert weekly.has_seasonality

    monthly = profile_series(seasonal_series(84, 3), MONTHLY)
    assert monthly.seasonal_period == 3
    assert monthly.has_seasonality


def test_flat_and_trending_series_are_not_called_seasonal() -> None:
    rng = np.random.default_rng(5)
    trend_only = 12_000 + 320 * np.arange(72) + rng.normal(0, 2_000, 72)

    profile = profile_series(trend_only, MONTHLY)
    assert not profile.has_seasonality
    assert profile.has_trend


def test_multiplicative_series_earns_a_log_transform() -> None:
    t = np.arange(72)
    multiplicative = 50_000 * (1.02**t) * (1 + 0.35 * np.sin(2 * np.pi * t / 12))
    additive = 50_000 + 900 * t + 6_000 * np.sin(2 * np.pi * t / 12)

    assert profile_series(multiplicative, MONTHLY).transform == "log"
    assert profile_series(additive, MONTHLY).transform == "none"


def test_transform_round_trips_within_tolerance() -> None:
    t = np.arange(60)
    values = 10_000 * (1.01**t)
    profile = profile_series(values, MONTHLY)
    transform = build_transform(values, profile)

    assert transform.active
    restored = transform.inverse(transform.forward(values))
    assert np.allclose(restored, values, rtol=0.05)


def test_series_with_many_zeros_is_flagged_intermittent() -> None:
    rng = np.random.default_rng(9)
    values = rng.poisson(3, 60).astype(float) * 120
    values[rng.random(60) < 0.5] = 0.0

    profile = profile_series(values, MONTHLY)
    assert profile.intermittent
    assert profile.transform == "none", "a log transform cannot apply to zeros"


def test_croston_is_offered_only_for_intermittent_demand() -> None:
    rng = np.random.default_rng(9)
    sparse = rng.poisson(3, 60).astype(float) * 120
    sparse[rng.random(60) < 0.5] = 0.0

    dense_kinds = {c.kind for c in build_candidates(MONTHLY, None, profile_series(seasonal_series(72, 12), MONTHLY))}
    sparse_kinds = {c.kind for c in build_candidates(MONTHLY, None, profile_series(sparse, MONTHLY))}

    assert ModelKind.CROSTON not in dense_kinds
    assert ModelKind.CROSTON in sparse_kinds


def test_intermittent_series_are_scored_on_absolute_error() -> None:
    assert "wmape" in metric_weights_for(False)
    assert "wmape" not in metric_weights_for(True)
    assert set(metric_weights_for(True)) == {"mae", "rmse"}


def test_empty_series_profiles_without_raising() -> None:
    profile = profile_series(np.array([]), MONTHLY)
    assert profile.n_observations == 0
    assert not profile.has_seasonality
    assert minimum_history(profile) >= 6


def _result(model: ModelKind, wmape: float, smape: float, rmse: float) -> BacktestResult:
    return BacktestResult(
        model=model,
        folds=[FoldResult(0, 10, 3, [1.0], [1.0])],
        mae=wmape,
        rmse=rmse,
        smape=smape,
        wmape=wmape,
    )


def test_one_diverged_candidate_cannot_flatten_the_ranking() -> None:
    results = [
        _result(ModelKind.NAIVE, 136.0, 60.0, 900.0),
        _result(ModelKind.CROSTON, 115.0, 190.0, 700.0),
        _result(ModelKind.HOLT_WINTERS, 120.0, 150.0, 780.0),
        _result(ModelKind.SEASONAL_NAIVE, 164.0, 70.0, 1_000.0),
        _result(ModelKind.THETA, 156.0, 180.0, 950.0),
        _result(ModelKind.SARIMAX, 3.9e20, 199.0, 4.0e20),
    ]

    selection = select_model(results, metric_weights={"wmape": 1.0})

    assert selection.winner is not None
    assert selection.winner.result.model is ModelKind.CROSTON, (
        "the lowest wMAPE must win even when another candidate diverged"
    )


def test_divergence_guard_rejects_runaway_forecasts() -> None:
    history = np.array([100.0, 110.0, 105.0, 120.0])

    assert _diverged(np.array([115.0, 118.0]), history) is None
    assert _diverged(np.array([1e12, 1e13]), history) is not None
    assert _diverged(np.array([np.nan, 1.0]), history) is not None


def test_penalty_scale_punishes_complexity_only_on_thin_history() -> None:
    assert penalty_scale(600, ModelKind.GRADIENT_BOOSTING) == 1.0
    assert penalty_scale(24, ModelKind.GRADIENT_BOOSTING) > 1.0
    assert penalty_scale(24, ModelKind.NAIVE) == 1.0
    assert penalty_scale(None, ModelKind.SARIMAX) == 1.0


def test_backtest_plan_follows_the_detected_period() -> None:
    short_period = plan_backtest(104, 8, WEEKLY, seasonal_period=13)
    default_period = plan_backtest(104, 8, WEEKLY)

    assert short_period.initial_train <= default_period.initial_train
    assert short_period.n_folds >= default_period.n_folds


def test_long_history_switches_to_a_rolling_window() -> None:
    assert plan_backtest(40, 6, MONTHLY, seasonal_period=12).scheme == "expanding"
    assert plan_backtest(400, 6, MONTHLY, seasonal_period=12).scheme == "rolling"


def test_run_reports_what_it_detected() -> None:
    values = seasonal_series(84, 3)
    periods = [add_periods(date(2020, 1, 1), i, MONTHLY) for i in range(values.size)]

    output = run_forecast(
        ForecastInput(
            series=SeriesInput(periods=periods, values=[float(v) for v in values]),
            frequency=MONTHLY,
            horizon=6,
        )
    )

    assert output.diagnostics["seasonal_period"] == 3
    assert output.diagnostics["folds"] >= 1
    assert output.diagnostics["backtest_scheme"] in {"expanding", "rolling"}
    assert output.metrics["seasonal_period"] == 3.0


def test_ets_searches_the_taxonomy_and_forecasts() -> None:
    values = seasonal_series(72, 12)
    periods = [add_periods(date(2020, 1, 1), i, MONTHLY) for i in range(values.size)]

    from app.forecasting.models import AutoEtsForecaster

    model = AutoEtsForecaster(MONTHLY, profile_series(values, MONTHLY))
    model.fit(values, periods)
    forecast = model.predict(6, [])

    assert forecast.size == 6
    assert np.all(np.isfinite(forecast))
    assert model.params["error"] in {"add", "mul"}
    assert np.isfinite(float(model.params["aicc"]))


def test_ensemble_combines_its_members() -> None:
    values = seasonal_series(72, 12)
    periods = [add_periods(date(2020, 1, 1), i, MONTHLY) for i in range(values.size)]

    from app.forecasting.models import EnsembleForecaster

    model = EnsembleForecaster(MONTHLY, profile_series(values, MONTHLY))
    model.fit(values, periods)
    forecast = model.predict(6, [add_periods(periods[-1], i, MONTHLY) for i in range(1, 7)])

    assert forecast.size == 6
    assert np.all(np.isfinite(forecast))
    assert len(model.params["members"]) >= 2
    assert model.params["combiner"] == "median"


def test_ensemble_refuses_to_run_on_a_single_member() -> None:
    from app.forecasting.models import EnsembleForecaster

    values = np.arange(20, dtype=float) + 100
    periods = [add_periods(date(2020, 1, 1), i, MONTHLY) for i in range(values.size)]

    model = EnsembleForecaster(MONTHLY, profile_series(values, MONTHLY), members=(ModelKind.THETA,))
    try:
        model.fit(values, periods)
    except ValueError as exc:
        assert "at least two members" in str(exc)
    else:
        raise AssertionError("a one-member combination should not be accepted")


def test_missing_optional_models_are_reported_not_hidden() -> None:
    from app.forecasting.models import ProphetForecaster, unavailable_models

    missing = unavailable_models()
    if ProphetForecaster.available():
        assert ModelKind.PROPHET not in missing
    else:
        assert ModelKind.PROPHET in missing
        assert "requirements-optional" in missing[ModelKind.PROPHET]
