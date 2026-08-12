"""Which models a series is allowed to reach.

A spreadsheet from a real business contains intermittent series. Exponential
smoothing fitted to demand that is zero four weeks in five reports a small
steady level with a tight interval, and it is wrong in the way that is hardest
to notice: it looks like a forecast.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.forecasting.diagnostics import profile_series
from app.forecasting.models import build_candidates
from app.forecasting.routing import (
    BASELINE_MODELS,
    ERRATIC,
    INTERMITTENT,
    LUMPY,
    NO_DEMAND,
    SMOOTH,
    SMOOTH_DEMAND_MODELS,
    classify,
    route,
)
from app.models.enums import ForecastFrequency, ModelKind

WEEKLY = ForecastFrequency.WEEKLY


def intermittent_series(n: int = 120, every: int = 5, size: float = 9.0) -> np.ndarray:
    y = np.zeros(n)
    y[::every] = size
    return y


def lumpy_series(n: int = 120, every: int = 5, seed: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    y = np.zeros(n)
    hits = np.arange(0, n, every)
    y[hits] = rng.gamma(shape=0.6, scale=30.0, size=hits.size)
    return y


def smooth_series(n: int = 120, seed: int = 2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 + rng.normal(0.0, 4.0, size=n)


class TestQuadrant:
    @pytest.mark.parametrize(
        ("adi", "cv2", "expected"),
        [
            (1.0, 0.2, SMOOTH),
            (1.0, 0.9, ERRATIC),
            (2.0, 0.2, INTERMITTENT),
            (2.0, 0.9, LUMPY),
            (1.31, 0.48, SMOOTH),
            (1.32, 0.49, LUMPY),
            (float("inf"), 0.0, NO_DEMAND),
        ],
    )
    def test_the_boundaries_are_where_syntetos_boylan_put_them(
        self, adi: float, cv2: float, expected: str
    ) -> None:
        assert classify(adi, cv2) == expected


class TestIntermittentNeverReachesASmoothModel:
    def test_the_classifier_recognises_intermittent_demand(self) -> None:
        profile = profile_series(intermittent_series(), WEEKLY)
        assert profile.demand_class == INTERMITTENT

    def test_the_roster_offered_to_an_intermittent_series_excludes_smooth_models(self) -> None:
        profile = profile_series(intermittent_series(), WEEKLY)

        kinds = {candidate.kind for candidate in build_candidates(WEEKLY, None, profile)}

        assert kinds & SMOOTH_DEMAND_MODELS == set()
        assert ModelKind.CROSTON in kinds
        assert kinds >= BASELINE_MODELS

    def test_a_lumpy_series_gets_the_same_treatment(self) -> None:
        profile = profile_series(lumpy_series(), WEEKLY)
        assert profile.demand_class == LUMPY

        kinds = {candidate.kind for candidate in build_candidates(WEEKLY, None, profile)}
        assert kinds & SMOOTH_DEMAND_MODELS == set()

    def test_a_smooth_series_still_reaches_the_smooth_models(self) -> None:
        profile = profile_series(smooth_series(), WEEKLY)
        assert profile.demand_class == SMOOTH

        kinds = {candidate.kind for candidate in build_candidates(WEEKLY, None, profile)}

        assert ModelKind.HOLT_WINTERS in kinds
        assert ModelKind.CROSTON not in kinds

    def test_baselines_survive_every_class(self) -> None:
        for series in (intermittent_series(), lumpy_series(), smooth_series()):
            profile = profile_series(series, WEEKLY)
            kinds = {candidate.kind for candidate in build_candidates(WEEKLY, None, profile)}
            assert kinds >= BASELINE_MODELS, profile.demand_class


class TestWhatMayBeClaimed:
    def test_a_lumpy_series_does_not_get_a_point_forecast_claim(self) -> None:
        routing = route(profile_series(lumpy_series(), WEEKLY))

        assert routing.demand_class == LUMPY
        assert routing.point_forecast_is_meaningful is False
        assert routing.widen_intervals is True

    def test_an_intermittent_series_keeps_its_point_forecast_but_widens(self) -> None:
        routing = route(profile_series(intermittent_series(), WEEKLY))

        assert routing.point_forecast_is_meaningful is True
        assert routing.widen_intervals is True

    def test_a_smooth_series_claims_both(self) -> None:
        routing = route(profile_series(smooth_series(), WEEKLY))

        assert routing.point_forecast_is_meaningful is True
        assert routing.widen_intervals is False

    def test_the_decision_is_retrievable_and_says_why(self) -> None:
        payload = route(profile_series(lumpy_series(), WEEKLY)).as_dict()

        assert payload["demand_class"] == LUMPY
        assert payload["point_forecast_is_meaningful"] is False
        assert isinstance(payload["reason"], str)
        assert "quantiles" in str(payload["reason"])
        assert ModelKind.HOLT_WINTERS.value not in payload["allowed_models"]

    def test_a_series_with_almost_no_demand_claims_nothing(self) -> None:
        barely = np.zeros(60)
        barely[3] = 5.0

        routing = route(profile_series(barely, WEEKLY))

        assert routing.demand_class == NO_DEMAND
        assert routing.point_forecast_is_meaningful is False
        assert routing.allowed == BASELINE_MODELS


class TestNoProfileIsNotAGate:
    def test_without_a_profile_every_candidate_is_still_offered(self) -> None:
        routing = route(None)

        assert ModelKind.HOLT_WINTERS in routing.allowed
        assert ModelKind.CROSTON in routing.allowed
