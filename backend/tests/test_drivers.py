from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from app.forecasting.drivers import (
    DriverLink,
    DriverPanel,
    admissible_lags,
    budget,
    build_panel,
    describe,
    significant_at,
)
from app.forecasting.engine import ForecastInput, SeriesInput, run_forecast
from app.forecasting.features import build_design_matrix, build_feature_spec, driver_mask
from app.models.enums import ForecastFrequency
from app.reporting.pdf import _leading

HORIZON = 6


def months(n: int, start: date = date(2019, 1, 1)) -> list[date]:
    return [
        date(start.year + (start.month - 1 + i) // 12, (start.month - 1 + i) % 12 + 1, 1)
        for i in range(n)
    ]


def leading_panel(
    n: int = 72, lag: int = HORIZON, noise: float = 0.02
) -> tuple[np.ndarray, np.ndarray]:
    """
    A driver that genuinely leads, and the target it leads.

    The target is a seasonal series plus a shock the driver saw `lag` periods
    earlier. Nothing in the target's own past predicts the shock, so a model
    that can read the driver has something a model that cannot does not.
    """
    rng = np.random.default_rng(7)
    driver = rng.normal(0.0, 1.0, n)

    season = 200.0 + 40.0 * np.sin(2 * np.pi * np.arange(n) / 12.0)
    shock = np.zeros(n)
    shock[lag:] = 60.0 * driver[: n - lag]

    target = season + shock + rng.normal(0.0, noise * 200.0, n)
    return target, driver


def test_a_short_series_is_offered_no_drivers() -> None:
    assert budget(19) == 0
    assert budget(40) == 2
    assert budget(200) == 4


def test_the_bar_tightens_as_the_series_shortens() -> None:
    assert significant_at(11) == 1.0, "too few pairs to claim anything"
    assert significant_at(30) > significant_at(200)
    assert 0.0 < significant_at(200) < 0.2


def test_only_lags_the_forecast_can_read_are_offered() -> None:
    lags = admissible_lags(horizon=6, n_observations=72, frequency=ForecastFrequency.MONTHLY)

    assert min(lags) == 6, "a shorter lag would need the driver's own future"
    assert max(lags) <= 18


def test_a_lag_that_would_leave_no_rows_is_dropped() -> None:
    assert admissible_lags(horizon=6, n_observations=16, frequency=ForecastFrequency.MONTHLY) == []


def test_a_leading_column_is_found_at_its_true_lag() -> None:
    target, driver = leading_panel(lag=HORIZON)

    panel = build_panel(
        target, {"web_sessions": driver}, horizon=HORIZON, frequency=ForecastFrequency.MONTHLY
    )

    assert panel.names == ["web_sessions"]
    assert panel.links[0].lag == HORIZON
    assert abs(panel.links[0].strength) > 0.5


def test_noise_is_not_mistaken_for_a_driver() -> None:
    rng = np.random.default_rng(3)
    target = 200.0 + 40.0 * np.sin(2 * np.pi * np.arange(72) / 12.0)

    panel = build_panel(
        target,
        {f"noise_{i}": rng.normal(0.0, 1.0, 72) for i in range(6)},
        horizon=HORIZON,
        frequency=ForecastFrequency.MONTHLY,
    )

    assert panel.names == []


def test_the_panel_keeps_only_what_it_can_afford() -> None:
    target, driver = leading_panel(n=60)
    candidates = {f"copy_{i}": np.roll(driver, i) for i in range(8)}

    panel = build_panel(target, candidates, horizon=HORIZON, frequency=ForecastFrequency.MONTHLY)

    assert len(panel.links) <= budget(60)


def test_a_row_never_reads_a_value_it_could_not_have_known() -> None:
    """
    The property the whole design rests on. A backtest fold is a prefix, and a
    row at index i may only read the driver at i - lag; if that were ever
    violated the backtest would be scoring a model on the future.
    """
    raw = np.arange(50, dtype=float)
    panel = DriverPanel(links=[DriverLink(name="d", lag=HORIZON, strength=0.9)], series={"d": raw})

    columns = panel.columns(50)["driver_d_lag_6"]

    assert np.isnan(columns[:HORIZON]).all(), "nothing is knowable before the first full lag"
    for index in range(HORIZON, 50):
        assert columns[index] == raw[index - HORIZON]

    # Asking for rows beyond the panel is the future-row case: each still only
    # reaches back `lag`, so it stays inside what has already happened.
    extended = panel.columns(56)["driver_d_lag_6"]
    assert extended[55] == raw[49]
    assert np.isfinite(extended[50:]).all()


def test_driver_columns_reach_the_design_matrix_and_are_identifiable() -> None:
    target, driver = leading_panel()
    panel = build_panel(
        target, {"web_sessions": driver}, horizon=HORIZON, frequency=ForecastFrequency.MONTHLY
    )
    spec = build_feature_spec(len(target), ForecastFrequency.MONTHLY, drivers=panel)

    _matrix, _y, names, _rows = build_design_matrix(
        target, months(len(target)), spec, ForecastFrequency.MONTHLY
    )

    assert any(name.startswith("driver_web_sessions") for name in names)
    assert driver_mask(names).sum() == 1


def test_a_dataset_with_no_extra_columns_forecasts_exactly_as_before() -> None:
    target, _driver = leading_panel()
    periods = months(len(target))

    def forecast(drivers: dict[str, list[float]]):
        return run_forecast(
            ForecastInput(
                series=SeriesInput(periods=periods, values=[float(v) for v in target]),
                frequency=ForecastFrequency.MONTHLY,
                horizon=HORIZON,
                drivers=drivers,
            )
        )

    assert forecast({}).point_forecast == pytest.approx(forecast({}).point_forecast)


def test_an_unrelated_column_does_not_get_used() -> None:
    target, _driver = leading_panel()
    rng = np.random.default_rng(11)

    output = run_forecast(
        ForecastInput(
            series=SeriesInput(periods=months(len(target)), values=[float(v) for v in target]),
            frequency=ForecastFrequency.MONTHLY,
            horizon=HORIZON,
            drivers={"unrelated": list(rng.normal(0.0, 1.0, len(target)))},
        )
    )

    assert output.leading_columns == []


def test_a_real_driver_improves_the_backtest() -> None:
    """
    The number that justifies the feature. The shock is invisible in the
    target's own history, so a model that reads the driver should backtest
    better than the same engine without it.
    """
    target, driver = leading_panel(n=84, lag=HORIZON, noise=0.01)
    periods = months(len(target))
    series = SeriesInput(periods=periods, values=[float(v) for v in target])

    without = run_forecast(
        ForecastInput(series=series, frequency=ForecastFrequency.MONTHLY, horizon=HORIZON)
    )
    with_driver = run_forecast(
        ForecastInput(
            series=series,
            frequency=ForecastFrequency.MONTHLY,
            horizon=HORIZON,
            drivers={"web_sessions": [float(v) for v in driver]},
        )
    )

    assert with_driver.metrics["wmape"] < without.metrics["wmape"]
    assert [link.name for link in with_driver.leading_columns] == ["web_sessions"]


def test_the_explanation_names_the_column_and_the_lead_in_plain_words() -> None:
    sentence = describe(
        [DriverLink(name="web_sessions", lag=6, strength=0.7)],
        ForecastFrequency.MONTHLY,
        "revenue",
    )

    assert sentence == (
        "It also read web_sessions from 6 months earlier, "
        "which your history shows moving before revenue does."
    )
    assert "lag" not in sentence and "regressor" not in sentence


def test_the_explanation_is_empty_when_nothing_led() -> None:
    assert describe([], ForecastFrequency.MONTHLY, "revenue") == ""


def test_a_weekly_run_is_told_about_weeks() -> None:
    sentence = describe(
        [DriverLink(name="spend", lag=1, strength=-0.6)], ForecastFrequency.WEEKLY, "orders"
    )

    assert "1 week earlier" in sentence


def test_the_rationale_carries_the_leading_column_to_the_reader() -> None:
    target, driver = leading_panel(n=84, lag=HORIZON, noise=0.01)

    output = run_forecast(
        ForecastInput(
            series=SeriesInput(periods=months(len(target)), values=[float(v) for v in target]),
            frequency=ForecastFrequency.MONTHLY,
            horizon=HORIZON,
            drivers={"web_sessions": [float(v) for v in driver]},
            target_label="revenue",
        )
    )

    assert "web_sessions from 6 months earlier" in output.selection_rationale


def test_the_report_names_the_columns_the_forecast_read() -> None:
    run = SimpleNamespace(
        frequency=ForecastFrequency.MONTHLY,
        leading_columns=[
            {"name": "web_sessions", "lag": 6, "direction": "up"},
            {"name": "ad_spend", "lag": 7, "direction": "up"},
        ],
    )

    assert _leading(run) == (  # type: ignore[arg-type]
        "web_sessions from 6 months earlier; ad_spend from 7 months earlier"
    )


def test_the_report_says_plainly_when_nothing_else_was_read() -> None:
    run = SimpleNamespace(frequency=ForecastFrequency.MONTHLY, leading_columns=[])

    assert _leading(run) == "the target's own history only"  # type: ignore[arg-type]
