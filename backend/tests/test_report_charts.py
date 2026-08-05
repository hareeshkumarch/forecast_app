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
from app.reporting.charts import ForecastChart, RiskChart, ScoreChart, _compact, _nice_ceiling

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


def _score_rows(*values: tuple[float, float]) -> list[tuple[date, float, float]]:
    calendar = _months(len(values))
    return [
        (period, forecast, actual)
        for period, (forecast, actual) in zip(calendar, values, strict=True)
    ]


@pytest.mark.parametrize(
    ("rows", "why"),
    [
        ([], "nothing scored yet"),
        (_score_rows((100.0, 120.0)), "the ordinary case"),
        (_score_rows((0.0, 0.0), (0.0, 0.0)), "a series that is flat zero"),
        # A margin, a net change, a churn delta: the measure is signed, and a
        # bar that cannot go below the axis draws these as hairlines at zero.
        (_score_rows((-50.0, -80.0), (30.0, -10.0)), "a measure that goes negative"),
        (_score_rows((1e9, 1.0)), "a forecast orders of magnitude out"),
    ],
)
def test_the_score_chart_draws_whatever_it_is_handed(
    rows: list[tuple[date, float, float]], why: str
) -> None:
    from reportlab.pdfgen.canvas import Canvas

    chart = ScoreChart(rows=rows, width=WIDTH, height=HEIGHT)
    chart.canv = Canvas("/dev/null")
    chart.draw()  # must not raise
    assert chart.wrap(WIDTH, 800.0) == (WIDTH, HEIGHT), why


def test_a_negative_bar_is_drawn_below_the_axis_not_flattened_onto_it() -> None:
    """
    Geometry rather than pixels: the rectangle for a negative value has to
    start below its baseline and have real height, which is what the first
    version — height clamped to a minimum — could not produce.
    """
    from reportlab.pdfgen.canvas import Canvas

    drawn: list[tuple[float, float, float, float]] = []

    class Recording(Canvas):
        def rect(self, x: float, y: float, w: float, h: float, **kwargs: object) -> None:
            drawn.append((x, y, w, h))

    chart = ScoreChart(rows=_score_rows((80.0, -60.0)), width=WIDTH, height=HEIGHT)
    chart.canv = Recording("/dev/null")
    chart.draw()

    # The bars are drawn before the legend swatches, which are also rectangles.
    forecast, actual = drawn[:2]
    assert forecast[3] > 1.0, "a positive bar rises from the baseline"
    assert actual[3] > 1.0, "and a negative one has height of its own"
    assert actual[1] < forecast[1], "the negative bar starts lower than the positive one"


def test_a_forecast_chart_draws_the_actuals_it_has_and_no_more() -> None:
    """A part-graded horizon is the normal case: some periods have finished."""
    from reportlab.pdfgen.canvas import Canvas

    for realized in (
        [],
        [None, None, None, None, None, None],
        [165.0, None, None, None, None, None],
    ):
        chart = _chart(realized=realized)
        chart.canv = Canvas("/dev/null")
        chart.draw()
