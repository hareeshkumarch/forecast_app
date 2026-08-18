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
from app.reporting.charts import (
    ForecastChart,
    PlanBand,
    RiskChart,
    ScoreChart,
    _compact,
    _nice_ceiling,
)

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
    assert _nice_ceiling(0.0) == 1.0
    assert _nice_ceiling(-5.0) == 1.0


def test_the_axis_does_not_double_itself_just_past_a_power_of_ten() -> None:
    # Rounding on the leading digit alone sent 1.01M to 2M, and every chart of
    # a series that had just crossed a power of ten drew itself in the bottom
    # half of an empty frame. Readable is not the only requirement: the axis
    # also has to be close enough to the data to be worth the ink.
    assert _nice_ceiling(1_010_000.0) == pytest.approx(1_200_000.0)
    assert _nice_ceiling(101_200.0) == pytest.approx(120_000.0)

    for value in (1.01, 17.0, 230.0, 4_900.0, 61_000.0, 780_000.0):
        assert _nice_ceiling(value) >= value
        assert _nice_ceiling(value) <= value * 1.4


def test_a_value_already_on_a_step_keeps_it() -> None:
    # A chart topping out at exactly 40,000 should not be drawn to 50,000.
    assert _nice_ceiling(40_000.0) == pytest.approx(40_000.0)
    assert _nice_ceiling(1_000_000.0) == pytest.approx(1_000_000.0)


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


# ------------------------------------------------------ the concentration cut


def test_a_cut_outside_the_bars_drawn_is_ignored() -> None:
    """A rule below the last bar describes nothing and looks like an axis."""
    from reportlab.pdfgen.canvas import Canvas

    rows = [("A", 90.0), ("B", 60.0), ("C", 30.0)]
    for cut in (None, 0, 3, 40):
        chart = RiskChart(rows=rows, width=WIDTH, height=60.0, cut=cut)
        chart.canv = Canvas("/dev/null")
        chart.draw()  # must not raise


def test_the_cut_rule_leaves_room_for_its_own_caption() -> None:
    # Drawn full width, the rule ran under the caption and the caption ran
    # through the bar above it. The rule now stops short of the text.
    from reportlab.pdfgen.canvas import Canvas

    chart = RiskChart(rows=[("A", 90.0), ("B", 60.0), ("C", 30.0)], width=WIDTH, height=60.0, cut=1)
    canvas = Canvas("/dev/null")
    chart.canv = canvas

    drawn: list[tuple[float, float, float, float]] = []
    canvas.line = lambda *args: drawn.append(args)  # type: ignore[method-assign]
    chart.draw()

    caption = canvas.stringWidth("HALF THE RISK IS ABOVE THIS LINE", "Helvetica-Bold", 6)
    assert drawn, "the cut should draw a rule"
    assert drawn[-1][2] <= WIDTH - caption


# ------------------------------------------------------------- the plan band


def test_the_plan_band_reserves_its_space() -> None:
    band = PlanBand(commit=80.0, base=100.0, prepare=130.0, width=WIDTH, height=70.0)

    assert band.wrap(WIDTH, 800.0) == (WIDTH, 70.0)


@pytest.mark.parametrize(
    ("commit", "base", "prepare", "why"),
    [
        (80.0, 100.0, 130.0, "an ordinary band"),
        (100.0, 100.0, 100.0, "a forecast with no interval, so all three collapse"),
        (80.0, 80.0, 130.0, "a base case hard against the lower bound"),
        (80.0, 130.0, 130.0, "a base case hard against the upper bound"),
        (-50.0, -20.0, 10.0, "a band that crosses zero"),
        (0.0, 0.0, 0.0, "a series forecast at nothing at all"),
    ],
)
def test_the_plan_band_draws_whatever_the_forecast_gives_it(
    commit: float, base: float, prepare: float, why: str
) -> None:
    from reportlab.pdfgen.canvas import Canvas

    band = PlanBand(commit=commit, base=base, prepare=prepare, width=WIDTH, height=70.0)
    band.canv = Canvas("/dev/null")
    band.draw()  # must not raise
    assert True, why


def test_the_middle_label_stays_inside_the_frame() -> None:
    """The base case sits where the forecast puts it, including at one end."""
    from reportlab.pdfgen.canvas import Canvas

    band = PlanBand(commit=80.0, base=80.0, prepare=130.0, width=WIDTH, height=70.0)
    canvas = Canvas("/dev/null")
    band.canv = canvas

    # The font is captured at call time: the band draws its caption and its
    # figure at two different sizes, and measuring both with one of them makes
    # the check pass or fail for the wrong reason.
    placed: list[tuple[float, str, str, float]] = []
    canvas.drawCentredString = lambda x, _y, text: placed.append(  # type: ignore[method-assign]
        (x, text, canvas._fontname, canvas._fontsize)
    )
    band.draw()

    assert placed, "the base case should be labelled"
    for x, text, font, size in placed:
        half = canvas.stringWidth(text, font, size) / 2
        assert x - half >= 0.0
        assert x + half <= WIDTH
