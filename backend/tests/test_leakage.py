from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.datasets.quality import align_calendar
from app.forecasting.backtest import BacktestPlan, run_backtest
from app.forecasting.frequency import add_periods
from app.forecasting.models import Forecaster
from app.forecasting.preparation import Preparation, fill_gaps, winsorise
from app.models.enums import ForecastFrequency, GapFill, ModelKind

MONTHLY = ForecastFrequency.MONTHLY


def months(n: int, start: date = date(2022, 1, 1)) -> list[date]:
    return [add_periods(start, i, MONTHLY) for i in range(n)]


class _RecordingModel(Forecaster):
    kind = ModelKind.NAIVE
    min_observations = 1

    def __init__(self, seen: list[np.ndarray]) -> None:
        self._seen = seen
        self._last = 0.0

    def fit(self, y, periods=None):  # type: ignore[no-untyped-def]
        self._seen.append(np.asarray(y, dtype=float).copy())
        self._last = float(y[-1])
        return self

    def predict(self, horizon, periods=None):  # type: ignore[no-untyped-def]
        return np.full(horizon, self._last)

    @property
    def params(self) -> dict[str, object]:
        return {}


def _training_windows(y: np.ndarray, plan: BacktestPlan, prepare: Preparation) -> list[np.ndarray]:
    seen: list[np.ndarray] = []
    run_backtest(
        lambda _y, _p: _RecordingModel(seen),
        ModelKind.NAIVE,
        y,
        months(y.size),
        plan,
        MONTHLY,
        prepare=prepare,
    )
    return seen


def _plan(n: int, horizon: int, cuts: list[int]) -> BacktestPlan:
    return BacktestPlan(scheme="expanding", horizon=horizon, cut_points=cuts, initial_train=cuts[0])


def test_a_gap_is_filled_from_the_past_alone() -> None:
    values = np.arange(24, dtype=float) * 10.0
    values[10] = np.nan

    prepared = Preparation(fill=GapFill.INTERPOLATE)
    windows = _training_windows(values, _plan(24, 6, [11, 17]), prepared)

    first_fold = windows[0]
    assert first_fold.size == 11
    assert first_fold[10] == pytest.approx(90.0)
    assert fill_gaps(values, GapFill.INTERPOLATE)[10] == pytest.approx(100.0)


def test_outliers_are_clipped_against_the_window_that_can_see_them() -> None:
    values = np.full(24, 100.0)
    values += np.arange(24, dtype=float)
    values[20] = 100_000.0

    prepared = Preparation(winsorise_sigmas=3.5)
    windows = _training_windows(values, _plan(24, 6, [12, 18]), prepared)

    for window in windows:
        assert float(np.max(window)) < 200.0

    whole = winsorise(values, 3.5)
    assert float(np.max(whole[:12])) == pytest.approx(float(np.max(windows[0])))


def test_a_period_that_was_never_observed_is_not_scored() -> None:
    values = np.arange(24, dtype=float) * 10.0
    values[[19, 20]] = np.nan

    result = run_backtest(
        lambda _y, _p: _RecordingModel([]),
        ModelKind.NAIVE,
        values,
        months(24),
        _plan(24, 6, [18]),
        MONTHLY,
        prepare=Preparation(fill=GapFill.INTERPOLATE),
    )

    assert result.n_folds == 1
    fold = result.folds[0]
    assert fold.test_size == 4
    assert all(np.isfinite(v) for v in fold.y_true)


def test_a_fold_whose_window_holds_no_observation_at_all_is_dropped() -> None:
    values = np.arange(24, dtype=float) * 10.0
    values[18:24] = np.nan

    result = run_backtest(
        lambda _y, _p: _RecordingModel([]),
        ModelKind.NAIVE,
        values,
        months(24),
        _plan(24, 6, [12, 18]),
        MONTHLY,
        prepare=Preparation(fill=GapFill.INTERPOLATE),
    )

    assert result.n_folds == 1
    assert result.folds[0].fold == 0


def test_a_driver_is_chosen_by_the_window_that_can_see_it() -> None:
    from app.forecasting.drivers import DriverSource

    calendar = months(48)
    rng = np.random.default_rng(11)
    target = np.concatenate([np.arange(24, dtype=float), rng.normal(12, 3, 24)])
    early = np.concatenate([np.arange(24, dtype=float) + 5.0, rng.normal(0, 5, 24)])
    late = np.concatenate([rng.normal(0, 5, 24), np.arange(24, dtype=float) * 2.0])

    source = DriverSource(
        periods=calendar,
        columns={"early": early, "late": late},
        horizon=3,
        frequency=MONTHLY,
    )

    first_half = source.panel_for(target[:24], calendar[:24])

    assert "late" not in first_half.names, (
        "a column that only leads the target after the cut must not be "
        "discoverable from a window that ends at the cut"
    )


def test_a_fold_panel_starts_where_the_fold_starts() -> None:
    from app.forecasting.drivers import DriverSource

    calendar = months(48)
    driver = np.arange(48, dtype=float) * 3.0
    target = np.arange(48, dtype=float)

    source = DriverSource(
        periods=calendar, columns={"traffic": driver}, horizon=3, frequency=MONTHLY
    )

    window = source.panel_for(target[24:], calendar[24:])

    if window:
        carried = window.series["traffic"]
        assert carried[0] == pytest.approx(driver[24])


def test_the_calendar_is_made_regular_without_filling_it() -> None:
    periods = [date(2022, 1, 1), date(2022, 2, 1), date(2022, 4, 1)]

    aligned = align_calendar(periods, [1.0, 2.0, 4.0], None, MONTHLY, GapFill.INTERPOLATE)

    assert aligned.periods == months(4)
    assert aligned.missing == [2]
    assert np.isnan(aligned.values[2]), "the hole stays a hole until somebody fits on it"


def test_asking_for_no_fill_keeps_the_series_on_its_own_index() -> None:
    periods = [date(2022, 1, 1), date(2022, 2, 1), date(2022, 4, 1)]

    aligned = align_calendar(periods, [1.0, 2.0, 4.0], None, MONTHLY, GapFill.NONE)

    assert aligned.periods == periods
    assert not aligned.regular
    assert all(np.isfinite(v) for v in aligned.values)
