"""Residual diagnostics: what is paired, what is bucketed, what is withheld."""

from __future__ import annotations

import datetime as dt

import numpy as np

from app.models.entities import ForecastPoint
from app.models.enums import PointKind
from app.services.diagnostic_service import MIN_RESIDUALS, histogram, pair


def _point(day: int, actual: float | None, forecast: float | None) -> ForecastPoint:
    return ForecastPoint(
        period=dt.date(2024, 1, 1) + dt.timedelta(days=day),
        kind=PointKind.FITTED,
        actual=actual,
        forecast=forecast,
    )


class TestPairing:
    def test_a_period_needs_both_sides_to_be_scored(self) -> None:
        points = [_point(0, 10.0, 9.0), _point(1, None, 11.0), _point(2, 12.0, None)]
        assert [row.period.day for row in pair(points)] == [1]

    def test_an_unscored_forecast_is_not_a_zero_error(self) -> None:
        """A forecast for next month has no outcome; counting it would flatter the model."""
        assert pair([_point(5, None, 100.0)]) == []

    def test_the_residual_is_forecast_minus_actual(self) -> None:
        (row,) = pair([_point(0, 10.0, 13.0)])
        assert row.residual == 3.0

    def test_pairs_come_back_in_time_order(self) -> None:
        points = [_point(4, 1.0, 1.0), _point(0, 2.0, 2.0), _point(2, 3.0, 3.0)]
        assert [row.period.day for row in pair(points)] == [1, 3, 5]

    def test_non_finite_readings_are_dropped(self) -> None:
        assert pair([_point(0, float("nan"), 5.0), _point(1, 5.0, float("inf"))]) == []


class TestHistogram:
    def _rows(self, residuals: list[float]):
        return pair([_point(index, 100.0, 100.0 + value) for index, value in enumerate(residuals)])

    def test_too_few_residuals_has_no_shape_to_show(self) -> None:
        assert histogram(self._rows([1.0, -1.0])) == []

    def test_the_buckets_are_centred_on_zero(self) -> None:
        """Otherwise the centre lands wherever the data sits and hides the lean."""
        buckets = histogram(self._rows([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))
        assert buckets
        assert buckets[0].start == -buckets[-1].end

    def test_every_residual_lands_in_a_bucket(self) -> None:
        values = [3.0, -2.0, 1.0, 0.5, -4.0, 2.5, 0.0]
        buckets = histogram(self._rows(values))
        assert sum(bucket.count for bucket in buckets) == len(values)

    def test_a_flawless_forecast_has_no_spread_to_draw(self) -> None:
        assert histogram(self._rows([0.0] * MIN_RESIDUALS)) == []

    def test_a_leaning_forecast_puts_its_weight_on_one_side(self) -> None:
        buckets = histogram(self._rows([2.0, 3.0, 4.0, 5.0, 6.0, 7.0]))
        midpoint = len(buckets) // 2
        below = sum(bucket.count for bucket in buckets[:midpoint])
        above = sum(bucket.count for bucket in buckets[midpoint:])
        assert above > below


class TestTheResidualsAgreeWithTheMetrics:
    def test_mean_absolute_residual_is_the_mae(self) -> None:
        rows = pair([_point(i, 10.0, 10.0 + d) for i, d in enumerate([1.0, -3.0, 2.0, -2.0])])
        residuals = np.array([row.residual for row in rows])
        actual = np.array([row.actual for row in rows])
        predicted = np.array([row.predicted for row in rows])

        from app.forecasting.metrics import mae

        assert float(np.mean(np.abs(residuals))) == mae(actual, predicted)
