"""The decision read off a forecast, and what it refuses to claim.

These are about the three numbers a plan needs — commit to, be ready for, and
how far ahead either holds — and about the actions being ordered by how much
of the plan they move rather than by how alarming they sound.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.forecasting.decisions import (
    Grade,
    Period,
    concentration_of,
    decide,
    grade_for,
    reliable_horizon,
)
from app.models.enums import ForecastFrequency

MONTHLY = ForecastFrequency.MONTHLY


def _periods(count: int = 6, *, spread: float = 0.1, forecast: float = 100.0) -> list[Period]:
    return [
        Period(
            period=date(2026, index + 1, 1),
            forecast=forecast,
            lower=forecast * (1 - spread),
            upper=forecast * (1 + spread),
            worst=forecast * (1 - spread * 1.4),
        )
        for index in range(count)
    ]


# ------------------------------------------------------------- the three numbers


def test_commit_is_the_floor_and_prepare_is_the_ceiling() -> None:
    # The point forecast is the middle of the distribution: committing to it is
    # right about half the time. The decision separates the promise from the
    # capacity, and the base case sits between them.
    decision = decide(_periods(), frequency=MONTHLY, confidence_level=0.8, accuracy=88.0)
    assert decision is not None

    assert decision.commit < decision.base < decision.prepare
    assert decision.commit == pytest.approx(6 * 90.0)
    assert decision.prepare == pytest.approx(6 * 110.0)


def test_a_forecast_with_no_band_does_not_invent_one() -> None:
    bare = [
        Period(period=date(2026, i + 1, 1), forecast=100.0, lower=None, upper=None)
        for i in range(4)
    ]
    decision = decide(bare, frequency=MONTHLY, confidence_level=0.8, accuracy=88.0)
    assert decision is not None

    assert decision.commit == decision.base == decision.prepare
    assert decision.spread_pct == 0.0


def test_nothing_to_decide_from_nothing() -> None:
    assert decide([], frequency=MONTHLY, confidence_level=0.8, accuracy=90.0) is None


# ------------------------------------------------------------------- the grading


@pytest.mark.parametrize(
    ("accuracy", "expected"),
    [
        (95.0, Grade.PLANNABLE),
        (75.0, Grade.PLANNABLE),
        (74.9, Grade.DIRECTIONAL),
        (55.0, Grade.DIRECTIONAL),
        (54.9, Grade.INDICATIVE),
        (None, Grade.INDICATIVE),
    ],
)
def test_grade_follows_measured_accuracy(accuracy: float | None, expected: Grade) -> None:
    assert grade_for(accuracy) is expected


def test_an_ungraded_forecast_says_so_rather_than_assuming_the_best() -> None:
    decision = decide(_periods(), frequency=MONTHLY, confidence_level=0.8, accuracy=None)
    assert decision is not None
    assert decision.grade is Grade.INDICATIVE
    assert "Do not set targets" in decision.actions[0].headline


# ------------------------------------------------------------ the useful horizon


def test_the_horizon_stops_at_the_first_period_that_fails() -> None:
    # Not a count of the good periods: a horizon is a run you can plan through,
    # and one narrow month behind three wide ones does not extend it.
    periods = [
        Period(date(2026, 1, 1), 100.0, 90.0, 110.0),
        Period(date(2026, 2, 1), 100.0, 85.0, 115.0),
        Period(date(2026, 3, 1), 100.0, 20.0, 180.0),
        Period(date(2026, 4, 1), 100.0, 98.0, 102.0),
    ]
    horizon = reliable_horizon(periods)

    assert horizon.periods == 2
    assert horizon.through == date(2026, 2, 1)
    assert horizon.covers_run is False


def test_a_band_that_stays_narrow_covers_the_whole_run() -> None:
    horizon = reliable_horizon(_periods(count=5, spread=0.08))
    assert horizon.periods == 5
    assert horizon.covers_run is True


def test_a_widening_band_asks_for_a_re_forecast() -> None:
    periods = [
        Period(date(2026, index + 1, 1), 100.0, 100.0 - index * 20, 100.0 + index * 20)
        for index in range(6)
    ]
    decision = decide(periods, frequency=MONTHLY, confidence_level=0.8, accuracy=90.0)
    assert decision is not None

    assert any("Re-forecast" in action.headline for action in decision.actions)


# ------------------------------------------------------------ where the risk sits


def test_concentration_counts_the_series_that_carry_half_the_risk() -> None:
    at_risk = [("A", 50.0), ("B", 30.0), ("C", 10.0), ("D", 10.0)]
    found = concentration_of(at_risk)

    assert found is not None
    assert found.count == 1
    assert found.total == 4
    assert found.share == pytest.approx(50.0)
    assert found.leaders == ["A"]


def test_a_flat_tail_of_exposure_is_not_reported_as_concentrated() -> None:
    found = concentration_of([(f"S{i}", 10.0) for i in range(10)])

    assert found is not None
    assert found.count == 5
    assert found.total == 10


def test_series_with_no_measured_risk_are_left_out() -> None:
    assert concentration_of([("A", 0.0), ("B", -1.0)]) is None
    assert concentration_of([]) is None


def test_risk_spread_evenly_across_every_series_raises_no_action() -> None:
    # count == total means "look at all of them", which is not a place to start.
    decision = decide(
        _periods(spread=0.02),
        frequency=MONTHLY,
        confidence_level=0.8,
        accuracy=92.0,
        at_risk=[("A", 10.0), ("B", 10.0)],
    )
    assert decision is not None
    assert not any("Start with" in action.headline for action in decision.actions)


# ------------------------------------------------------------------- the actions


def test_a_repeatable_lean_is_the_first_thing_to_fix() -> None:
    # It changes every number below it, so it outranks everything else.
    decision = decide(
        _periods(),
        frequency=MONTHLY,
        confidence_level=0.8,
        accuracy=90.0,
        realized_bias=8.0,
        realized_wmape=10.0,
    )
    assert decision is not None

    assert decision.lean_pct == pytest.approx(8.0)
    assert decision.actions[0].headline == "Correct the plan 8.0% down"


def test_scatter_is_not_reported_as_a_lean() -> None:
    decision = decide(
        _periods(),
        frequency=MONTHLY,
        confidence_level=0.8,
        accuracy=90.0,
        realized_bias=1.0,
        realized_wmape=12.0,
    )
    assert decision is not None

    assert decision.lean_pct is None
    assert not any("Correct the plan" in action.headline for action in decision.actions)


def test_an_interval_that_did_not_hold_is_called_out() -> None:
    decision = decide(
        _periods(),
        frequency=MONTHLY,
        confidence_level=0.95,
        accuracy=90.0,
        realized_coverage=52.0,
    )
    assert decision is not None

    assert any("Widen the range" in action.headline for action in decision.actions)


def test_a_clean_run_still_says_what_to_do() -> None:
    # An empty action list reads as a missing section rather than as good news.
    decision = decide(
        _periods(spread=0.02),
        frequency=MONTHLY,
        confidence_level=0.8,
        accuracy=94.0,
    )
    assert decision is not None

    assert decision.grade is Grade.PLANNABLE
    assert decision.actions[0].headline == "Commit to the plan as it stands"


def test_actions_are_ordered_by_what_they_move() -> None:
    decision = decide(
        [
            Period(date(2026, index + 1, 1), 100.0, 100.0 - index * 22, 100.0 + index * 22, 60.0)
            for index in range(6)
        ],
        frequency=MONTHLY,
        confidence_level=0.8,
        accuracy=60.0,
        at_risk=[("A", 90.0), ("B", 5.0), ("C", 5.0)],
        realized_bias=9.0,
        realized_wmape=12.0,
        realized_coverage=40.0,
    )
    assert decision is not None

    urgency = [action.urgency for action in decision.actions]
    assert urgency == sorted(urgency)
    assert decision.actions[0].headline.startswith("Correct the plan")


def test_a_downside_worth_covering_is_sized_in_the_plan_s_own_terms() -> None:
    periods = [
        Period(date(2026, index + 1, 1), 100.0, 88.0, 112.0, worst=70.0) for index in range(4)
    ]
    decision = decide(periods, frequency=MONTHLY, confidence_level=0.8, accuracy=90.0)
    assert decision is not None

    assert decision.exposure == pytest.approx(120.0)
    assert decision.downside_pct == pytest.approx(30.0)
    assert any("Hold cover" in action.headline for action in decision.actions)


def test_a_downside_inside_the_noise_is_not_dressed_up_as_a_risk() -> None:
    periods = [
        Period(date(2026, index + 1, 1), 100.0, 96.0, 104.0, worst=98.0) for index in range(4)
    ]
    decision = decide(periods, frequency=MONTHLY, confidence_level=0.8, accuracy=90.0)
    assert decision is not None

    assert not any("Hold cover" in action.headline for action in decision.actions)
