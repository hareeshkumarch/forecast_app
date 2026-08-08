"""What a fold is allowed to know.

A backtest is a claim about how the model would have done at the time. Every
step that looks at the values around a point — interpolating a gap, clipping an
outlier, ranking a driver — breaks that claim if it is done once over the whole
history, because the fold is then trained on numbers derived from the very
periods it is about to be scored against.

The leak does not announce itself. It makes the reported accuracy better than
the real one, which is the direction nobody investigates.
"""

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
    """A model that remembers exactly what it was trained on."""

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
    """np.interp over the whole series pulls the value after the gap backwards.

    A hole at period 10 filled from the whole history is the average of
    periods 9 and 11 — and period 11 is in the validation window of the fold
    that trains up to period 11.
    """
    values = np.arange(24, dtype=float) * 10.0
    values[10] = np.nan

    prepared = Preparation(fill=GapFill.INTERPOLATE)
    windows = _training_windows(values, _plan(24, 6, [11, 17]), prepared)

    first_fold = windows[0]
    assert first_fold.size == 11
    # The training window ends at period 10, which is the hole itself, so
    # there is nothing to its right and it carries period 9 forward.
    assert first_fold[10] == pytest.approx(90.0)
    # The whole-series fill would have used period 11 and produced 100.0.
    assert fill_gaps(values, GapFill.INTERPOLATE)[10] == pytest.approx(100.0)


def test_outliers_are_clipped_against_the_window_that_can_see_them() -> None:
    """A spike in the validation window must not move the training window's ceiling."""
    values = np.full(24, 100.0)
    values += np.arange(24, dtype=float)
    values[20] = 100_000.0

    prepared = Preparation(winsorise_sigmas=3.5)
    windows = _training_windows(values, _plan(24, 6, [12, 18]), prepared)

    # Neither training window contains the spike, so neither has its ceiling
    # dragged up by it. Winsorising the whole series first raises the clip for
    # every fold, and the folds are then trained on a series shaped by a value
    # they are supposed not to have seen.
    for window in windows:
        assert float(np.max(window)) < 200.0

    whole = winsorise(values, 3.5)
    assert float(np.max(whole[:12])) == pytest.approx(float(np.max(windows[0])))


def test_a_period_that_was_never_observed_is_not_scored() -> None:
    """Filling a gap invents a number; scoring against it reports an accuracy
    nobody measured, in whichever direction the filling happened to guess."""
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
    # Six periods in the window, two of them never reported.
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
    """A wide panel of candidates always contains one that fits the future.

    Ranking them once over the whole history picks the lag that best explains
    the periods being scored — which is the fastest way to a backtest that
    looks excellent and a forecast that is not.
    """
    from app.forecasting.drivers import DriverSource

    calendar = months(48)
    # A column that leads the target for the first half of the history and
    # goes to noise afterwards, and one that does the opposite.
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
    """A rolling fold begins partway through. A panel indexed from the series
    start would hand it driver values from the wrong periods entirely."""
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
