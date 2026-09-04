"""Validation judges each series against what that series needs."""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl

from app.models.enums import ForecastFrequency
from app.schema.validation import _level_shift, validate_canonical

WEEKLY = ForecastFrequency.WEEKLY


def _frame(**series: np.ndarray) -> pl.DataFrame:
    start = dt.date(2024, 1, 1)
    rows = [
        {
            "series_id": name,
            "ds": start + dt.timedelta(weeks=index),
            "y": float(value),
        }
        for name, values in series.items()
        for index, value in enumerate(values)
    ]
    return pl.DataFrame(rows)


def _codes(report, series_id: str) -> set[str]:
    return set(report.by_id[series_id].codes)


def _steady(n: int = 40, seed: int = 3) -> np.ndarray:
    return 50 + np.random.default_rng(seed).normal(0, 1, n)


def _stepped(seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.concatenate([np.full(20, 20.0), np.full(20, 90.0)]) + rng.normal(0, 1, 40)


def _trending(seed: int = 3) -> np.ndarray:
    return np.arange(40) * 2.0 + np.random.default_rng(seed).normal(0, 1, 40)


class TestALevelShiftIsAStepNotASlope:
    def test_a_genuine_step_is_found(self) -> None:
        assert _level_shift(_stepped()) == 20

    def test_a_straight_trend_is_not_a_step(self) -> None:
        assert _level_shift(_trending()) is None

    def test_a_seasonal_arc_is_not_a_step(self) -> None:
        rng = np.random.default_rng(3)
        arc = 100 + 40 * np.sin(np.arange(30) * 2 * np.pi / 52) + rng.normal(0, 2, 30)
        assert _level_shift(arc) is None

    def test_flat_history_has_no_step(self) -> None:
        assert _level_shift(_steady()) is None

    def test_a_step_inside_the_noise_is_not_reported(self) -> None:
        rng = np.random.default_rng(3)
        faint = np.concatenate([np.full(20, 50.0), np.full(20, 51.0)]) + rng.normal(0, 1, 40)
        assert _level_shift(faint) is None

    def test_too_little_history_to_judge(self) -> None:
        assert _level_shift(np.array([1.0, 9.0, 1.0, 9.0])) is None


class TestTheReportFollowsTheSeries:
    def test_a_step_is_reported_only_when_adaptive(self) -> None:
        frame = _frame(stepped=_stepped())
        assert "level_shift" in _codes(validate_canonical(frame, frequency=WEEKLY), "stepped")
        fixed = validate_canonical(frame, frequency=WEEKLY, adaptive=False)
        assert "level_shift" not in _codes(fixed, "stepped")

    def test_a_trending_series_is_not_warned_about(self) -> None:
        frame = _frame(trending=_trending())
        assert "level_shift" not in _codes(validate_canonical(frame, frequency=WEEKLY), "trending")

    def test_each_series_carries_what_it_needed(self) -> None:
        report = validate_canonical(_frame(steady=_steady()), frequency=WEEKLY)
        assert report.by_id["steady"].required_history is not None

    def test_the_profile_the_checks_used_is_reported(self) -> None:
        report = validate_canonical(_frame(steady=_steady()), frequency=WEEKLY)
        profile = report.by_id["steady"].profile
        assert profile is not None
        assert "demand_class" in profile

    def test_an_explicit_floor_still_wins(self) -> None:
        report = validate_canonical(_frame(steady=_steady()), frequency=WEEKLY, min_history=99)
        assert report.by_id["steady"].required_history == 99
        assert "short_history" in _codes(report, "steady")

    def test_the_fixed_path_carries_no_profile(self) -> None:
        report = validate_canonical(_frame(steady=_steady()), frequency=WEEKLY, adaptive=False)
        assert report.by_id["steady"].profile is None

    def test_bursty_demand_is_still_routed_to_the_fallback(self) -> None:
        rng = np.random.default_rng(3)
        bursty = np.where(rng.random(40) < 0.75, 0.0, rng.integers(1, 9, 40).astype(float))
        report = validate_canonical(_frame(bursty=bursty), frequency=WEEKLY)
        assert report.by_id["bursty"].route == "fallback"

    def test_a_healthy_series_stays_clean_under_both_paths(self) -> None:
        frame = _frame(steady=_steady(seed=11))
        for adaptive in (True, False):
            report = validate_canonical(frame, frequency=WEEKLY, adaptive=adaptive)
            assert report.by_id["steady"].status != "reject"
