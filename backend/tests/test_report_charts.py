"""
The drawn parts of the report.

A chart that silently collapses still produces a valid PDF, so these check the
geometry rather than the return code — the first version of these flowables
called `Flowable.__init__` after setting width and height, which zeroed both
and smeared the chart across the title.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.forecasting.frequency import add_periods
from app.models.enums import ForecastFrequency
from app.reporting.charts import ForecastChart, RiskChart, _compact, _nice_ceiling

MONTHLY = ForecastFrequency.MONTHLY
WIDTH, HEIGHT = 480.0, 150.0


def _months(count: int) -> list[date]:
    return [add_periods(date(2024, 1, 1), i, MONTHLY) for i in range(count)]


def _chart(**overrides: object) -> ForecastChart:
    calendar = _months(18)
    settings: dict[str, object] = {
        "history": [(period, 100.0 + i * 5) for i, period in enumerate(calendar[:12])],
        "forecast": [(period, 160.0 + i * 5) for i, period in enumerate(calendar[12:])],
        "lower": [150.0 + i * 5 for i in range(6)],
        "upper": [170.0 + i * 5 for i in range(6)],
        "width": WIDTH,
        "height": HEIGHT,
    }
    settings.update(overrides)
    return ForecastChart(**settings)  # type: ignore[arg-type]


def test_a_chart_reserves_the_space_it_was_given() -> None:
    chart = _chart()

    # ReportLab asks the flowable how much room it needs; a chart that answers
    # zero is laid out on top of whatever precedes it.
    assert chart.wrap(WIDTH, 800.0) == (WIDTH, HEIGHT)
    assert chart.width == WIDTH and chart.height == HEIGHT


def test_a_risk_chart_reserves_its_space_too() -> None:
    chart = RiskChart(rows=[("North · A", 500.0), ("South · B", 250.0)], width=WIDTH, height=60.0)

    assert chart.wrap(WIDTH, 800.0) == (WIDTH, 60.0)
    assert chart.width == WIDTH and chart.height == 60.0


@pytest.mark.parametrize(
    ("chart", "why"),
    [
        (_chart(history=[], forecast=[], lower=[], upper=[]), "nothing at all"),
        (_chart(lower=[], upper=[]), "a forecast with no band"),
        (_chart(history=[]), "a forecast with no history behind it"),
        (_chart(forecast=[], lower=[], upper=[]), "history with nothing ahead of it"),
        (
            _chart(
                history=[(date(2024, 1, 1), 0.0)] * 12,
                forecast=[(date(2025, 1, 1), 0.0)] * 6,
                lower=[0.0] * 6,
                upper=[0.0] * 6,
            ),
            "a series that is flat zero",
        ),
    ],
)
def test_a_chart_draws_whatever_it_is_handed(chart: ForecastChart, why: str) -> None:
    """None of these are worth an exception: the report still has to render."""
    from reportlab.pdfgen.canvas import Canvas

    chart.canv = Canvas("/dev/null")
    chart.draw()  # must not raise
    assert True, why


def test_a_risk_chart_survives_an_empty_and_a_zero_ranking() -> None:
    from reportlab.pdfgen.canvas import Canvas

    for rows in ([], [("Only", 0.0)], [("A", 0.0), ("B", 0.0)]):
        chart = RiskChart(rows=rows, width=WIDTH, height=40.0)
        chart.canv = Canvas("/dev/null")
        chart.draw()


def test_the_axis_rounds_up_to_something_readable() -> None:
    # Derived from each number's own magnitude, so it reads sensibly for
    # revenue in millions and for a conversion rate alike.
    assert _nice_ceiling(38_700.0) == 40_000.0
    assert _nice_ceiling(0.037) == pytest.approx(0.04)
    assert _nice_ceiling(1_010_000.0) == 2_000_000.0
    assert _nice_ceiling(0.0) == 1.0
    assert _nice_ceiling(-5.0) == 1.0


def test_axis_labels_stay_short_enough_to_read() -> None:
    assert _compact(1_500_000.0, currency=True) == "$1.5M"
    assert _compact(2_400_000_000.0, currency=True) == "$2.4B"
    assert _compact(950.0, currency=False) == "950"
    assert _compact(-1_200.0, currency=True) == "-$1.2K"
    assert _compact(0.0, currency=True) == "$0"
