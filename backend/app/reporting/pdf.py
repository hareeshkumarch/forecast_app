"""
The forecast as something you can hand to someone.

A CSV is for work that continues; this is for work that is being reported.
It carries the horizon, how the forecast was arrived at, how accurate the
method has been, and the breakdowns — in that order, because that is the
order the questions get asked in.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.database.base import utcnow
from app.datasets.profiler import is_currency_like
from app.forecasting.drivers import PERIOD_WORDS
from app.forecasting.frequency import comparison_window
from app.forecasting.metrics import accuracy_from_wmape, intervals_held
from app.models.entities import ForecastRun
from app.reporting.charts import ForecastChart, RiskChart, ScoreChart
from app.reporting.palette import ACCENT, BAND, FAINT, INK, MUTED, RULE

#: Matches `exporter.TOP_LINE` — a point that belongs to the run, not a series.
TOP_LINE = "Total"

#: Bars in the risk chart. Past this the picture stops being scannable and the
#: table underneath is the better way to read the tail.
RISK_BARS = 12
CHART_HEIGHT = 52 * mm

#: The share of realized error that has to point one way before the report
#: calls it a lean. A half is where the misses stop cancelling each other out —
#: expressed against the run's own error rather than as a fixed percentage, so
#: it means the same thing for a volatile series and a steady one.
DIRECTIONAL_SHARE = 0.5

MARGIN = 16 * mm


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle(
            "title", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=INK
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base, fontSize=9, leading=13, textColor=FAINT, spaceAfter=10
        ),
        "section": ParagraphStyle(
            "section",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=11,
            textColor=MUTED,
            spaceBefore=14,
            spaceAfter=5,
            alignment=TA_LEFT,
        ),
        "body": ParagraphStyle("body", parent=base, fontSize=8.5, leading=12, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8, leading=10.5, textColor=INK),
        "cellRight": ParagraphStyle(
            "cellRight", parent=base, fontSize=8, leading=10.5, textColor=INK, alignment=TA_RIGHT
        ),
    }


#: Beyond this a cell is wrapped rather than drawn as a single line. ReportLab
#: only reflows Paragraphs — a plain string is drawn at full width whatever the
#: column is, so a long model rationale ran off both edges of the page.
WRAP_OVER = 24


def _number(value: Any, digits: int = 0) -> str:
    """Numbers are read down a column, so they align and never show as None."""
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _percent(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def _signed(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _leading(run: ForecastRun) -> str:
    """
    The customer's own columns the forecast read, beside the target's history.

    Named in the report because a planner asked to trust a number wants to know
    what went into it, and "we also read your web sessions from six months
    earlier" is a far better answer than a model name.
    """
    columns = run.leading_columns or []
    if not columns:
        return "the target's own history only"

    singular, plural = PERIOD_WORDS.get(run.frequency, ("period", "periods"))
    parts = []
    for column in columns:
        lag = int(column.get("lag", 0))
        parts.append(
            f"{column.get('name', '?')} from {lag} {singular if lag == 1 else plural} earlier"
        )
    return "; ".join(parts)


def _when(value: date | None) -> str:
    return value.isoformat() if value else "—"


def _table(
    header: list[str],
    body: list[list[str]],
    widths: list[float],
    style: dict[str, ParagraphStyle] | None = None,
) -> Table:
    if style is not None:
        body = [
            [
                Paragraph(cell, style["cell"] if column == 0 else style["cellRight"])
                if column == 0 or len(cell) > WRAP_OVER
                else cell
                for column, cell in enumerate(row)
            ]
            for row in body
        ]

    table = Table([header, *body], colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
                ("TEXTCOLOR", (0, 1), (-1, -1), INK),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
                ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _chrome(canvas: Any, document: Any, run_name: str) -> None:
    """A rule and a page number on every page, so loose sheets stay identifiable."""
    canvas.saveState()
    width, _height = A4

    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 12 * mm, width - MARGIN, 12 * mm)

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(FAINT)
    canvas.drawString(MARGIN, 8 * mm, run_name[:70])
    canvas.drawRightString(width - MARGIN, 8 * mm, f"Page {document.page}")
    canvas.restoreState()


def build(
    path: Path,
    run: ForecastRun,
    rows: list[dict[str, Any]],
    sheets: dict[str, list[dict[str, Any]]],
    *,
    max_rows: int,
) -> None:
    style = _styles()
    width = A4[0] - 2 * MARGIN
    story: list[Any] = []

    currency = is_currency_like(run.target_column)
    unit = f"{run.target_column}{' (currency)' if currency else ''}"

    story.append(Paragraph(run.name, style["title"]))
    story.append(
        Paragraph(
            f"{run.frequency.value.title()} · {run.horizon} periods ahead · "
            f"generated {utcnow():%d %b %Y %H:%M} UTC",
            style["subtitle"],
        )
    )

    # The shape of the thing, before any of the numbers describing it.
    chart = _forecast_chart(rows, run, width, currency)
    if chart is not None:
        story.append(chart)
        story.append(Spacer(1, 4))

    # ---- how it was made
    story.append(Paragraph("HOW THIS FORECAST WAS MADE", style["section"]))
    grain = ", ".join(run.group_by) if run.group_by else "one total series"
    story.append(
        _table(
            ["", ""],
            [
                [
                    "Model selected",
                    _humanise(run.selected_model.value if run.selected_model else None),
                ],
                ["Why", run.selection_rationale or "—"],
                ["Measure", unit],
                ["Also read", _leading(run)],
                ["Forecast grain", grain],
                ["Series forecast", _number(run.series_count or 1)],
                ["History", f"{_when(run.history_start)} to {_when(run.history_end)}"],
                ["Horizon", f"{_when(run.forecast_start)} to {_when(run.forecast_end)}"],
                ["Interval", f"{run.confidence_level * 100:.0f}% confidence"],
                ["Missing periods", run.gap_fill.value],
                ["Duplicate periods", f"combined by {run.aggregation.value}"],
            ],
            [42 * mm, width - 42 * mm],
            style,
        )
    )

    if run.used_fallback and run.fallback_reason:
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                f"<b>Read with care.</b> {run.fallback_reason}",
                ParagraphStyle("warn", parent=style["body"], textColor=ACCENT),
            )
        )

    # ---- how it actually did, where the horizon has been lived through
    #
    # Before the backtest section deliberately: when both exist this is the
    # number that answers the question, and a backtest figure read first tends
    # to be the one that gets remembered.
    story.extend(_scorecard_section(run, rows, width, currency, style))

    # ---- how well it has done
    metrics = sheets.get("metrics") or []
    if metrics:
        story.append(Paragraph("MEASURED ACCURACY", style["section"]))
        story.append(
            Paragraph(
                "Every figure below comes from backtesting: the model was refitted on earlier "
                "windows and scored against periods it had not seen — what the method can be "
                "expected to do, rather than what this forecast turned out to do.",
                style["body"],
            )
        )
        story.append(Spacer(1, 5))
        story.append(
            _table(
                ["Metric", "Value", "Previous run"],
                [
                    [
                        _humanise(m["name"]),
                        _percent(m["value"]) if m["unit"] == "percent" else _number(m["value"], 2),
                        (
                            _percent(m["previous_value"])
                            if m["unit"] == "percent"
                            else _number(m["previous_value"], 2)
                        ),
                    ]
                    for m in metrics
                ],
                [width - 68 * mm, 34 * mm, 34 * mm],
                style,
            )
        )

    # ---- the horizon itself
    #
    # The run's own line only. A grouped run also stores a curve per series, and
    # mixing them in gives a column of identical dates with no way to tell which
    # series each row belongs to — the series get their own section below.
    horizon = [
        row
        for row in rows
        if row.get("kind") == "forecast" and row.get("series", TOP_LINE) == TOP_LINE
    ]
    if horizon:
        story.append(PageBreak())
        story.append(Paragraph("THE FORECAST", style["section"]))
        shown = horizon[:max_rows]
        story.append(
            _table(
                ["Period", "Forecast", "Low", "High", "Best case", "Worst case"],
                [
                    [
                        str(row.get("period", "")),
                        _number(row.get("forecast")),
                        _number(row.get("lower_bound")),
                        _number(row.get("upper_bound")),
                        _number(row.get("best_case")),
                        _number(row.get("worst_case")),
                    ]
                    for row in shown
                ],
                [30 * mm, *([(width - 30 * mm) / 5] * 5)],
                style,
            )
        )
        if len(horizon) > len(shown):
            story.append(Spacer(1, 5))
            story.append(
                Paragraph(
                    f"Showing the first {len(shown):,} of {len(horizon):,} periods. "
                    "The CSV export carries every one.",
                    style["body"],
                )
            )

    # ---- the breakdowns
    for title, key, columns in (
        ("BY REGION", "regions", ("region", "forecast", "change_vs_last_year_pct", "accuracy_pct")),
        (
            "BY CATEGORY",
            "categories",
            ("category", "forecast", "share_pct", "change_vs_last_year_pct"),
        ),
    ):
        data = sheets.get(key) or []
        if not data:
            continue
        story.append(
            KeepTogether(
                [
                    Paragraph(title, style["section"]),
                    _table(
                        [_humanise(c) for c in columns],
                        [
                            [
                                str(row.get(columns[0], "")),
                                _number(row.get(columns[1])),
                                (
                                    _signed(row.get(columns[2]))
                                    if columns[2].endswith("_pct") and "change" in columns[2]
                                    else _percent(row.get(columns[2]))
                                ),
                                (
                                    _signed(row.get(columns[3]))
                                    if "change" in columns[3]
                                    else _percent(row.get(columns[3]))
                                ),
                            ]
                            for row in data[:max_rows]
                        ],
                        [width - 96 * mm, 32 * mm, 32 * mm, 32 * mm],
                        style,
                    ),
                ]
            )
        )

    # ---- what needs a human, if the run had a grain
    series = sheets.get("series") or []
    if series:
        shown = series[:max_rows]
        story.append(
            KeepTogether(
                [
                    Paragraph("SERIES AT RISK", style["section"]),
                    Paragraph(
                        "Forecast multiplied by the error measured on that series — the ones "
                        "worth a week's attention, largest first. A series with no measured "
                        "error was apportioned from its parent rather than fitted.",
                        style["body"],
                    ),
                    Spacer(1, 6),
                    RiskChart(
                        rows=[
                            (str(row.get("series", "")), float(row.get("value_at_risk") or 0.0))
                            for row in shown
                            if row.get("value_at_risk")
                        ][:RISK_BARS],
                        width=width,
                        height=min(len(shown), RISK_BARS) * 6 * mm,
                        currency=currency,
                    ),
                    Spacer(1, 8),
                    _table(
                        ["Series", "Forecast", "Error", "At risk"],
                        [
                            [
                                str(row.get("series", "")),
                                _number(row.get("forecast")),
                                _percent(row.get("wmape_pct")) if row.get("measured") else "—",
                                _number(row.get("value_at_risk")),
                            ]
                            for row in shown
                        ],
                        [width - 96 * mm, 32 * mm, 32 * mm, 32 * mm],
                        style,
                    ),
                ]
            )
        )
        if len(series) > len(shown):
            story.append(Spacer(1, 5))
            story.append(
                Paragraph(
                    f"Showing the {len(shown):,} highest of {len(series):,} series.",
                    style["body"],
                )
            )

    drivers = sheets.get("drivers") or []
    if drivers:
        story.append(
            KeepTogether(
                [
                    Paragraph("WHAT IS MOVING IT", style["section"]),
                    _table(
                        ["Driver", "Impact", "Share", "Direction"],
                        [
                            [
                                str(row.get("driver", "")),
                                _number(row.get("impact")),
                                _percent(row.get("impact_pct")),
                                str(row.get("direction") or "—"),
                            ]
                            for row in drivers[:max_rows]
                        ],
                        [width - 96 * mm, 32 * mm, 32 * mm, 32 * mm],
                        style,
                    ),
                ]
            )
        )

    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=20 * mm,
        title=run.name,
        author="Forecast Hub",
        subject=f"Forecast for {run.target_column}",
    )

    def decorate(canvas: Any, doc: Any) -> None:
        _chrome(canvas, doc, run.name)

    document.build(story, onFirstPage=decorate, onLaterPages=decorate)


def _scorecard_section(
    run: ForecastRun,
    rows: list[dict[str, Any]],
    width: float,
    currency: bool,
    style: dict[str, ParagraphStyle],
) -> list[Any]:
    """
    How the forecast actually did, where the horizon has been lived through.

    Absent entirely until the run has been scored — an empty section headed
    "how it did" reads as a failure rather than as a horizon still running.
    """
    if run.scored_at is None or not run.scored_periods:
        return []

    graded = _graded_periods(rows)
    if not graded:
        return []

    accuracy = None if run.realized_wmape is None else accuracy_from_wmape(run.realized_wmape)
    forecast_total = sum(forecast for _, forecast, _ in graded)
    actual_total = sum(actual for _, _, actual in graded)

    measures = [
        ["Accuracy", _percent(accuracy)],
        ["Error (wMAPE)", _percent(run.realized_wmape)],
        ["Average miss", _number(run.realized_mae)],
        ["Bias", _signed(run.realized_bias)],
        ["Periods graded", f"{run.scored_periods} of {run.horizon}"],
        ["Forecast", _number(forecast_total)],
        ["Actual", _number(actual_total)],
    ]
    if run.realized_coverage is not None:
        measures.insert(
            4,
            [
                f"Inside the {run.confidence_level * 100:.0f}% interval",
                _percent(run.realized_coverage, 0),
            ],
        )

    lede = (
        "Measured against what happened, not against a backtest. "
        f"{'Every period' if run.scored_periods >= run.horizon else 'Only the periods'} "
        "that had finished when this was scored is included; a period still being "
        "lived through is left out rather than compared against part of itself."
    )
    verdict = _verdict(run)

    return [
        KeepTogether(
            [
                Paragraph("HOW THIS FORECAST ACTUALLY DID", style["section"]),
                Paragraph(lede, style["body"]),
                Spacer(1, 6),
                ScoreChart(
                    rows=graded,
                    width=width,
                    height=CHART_HEIGHT,
                    currency=currency,
                ),
                Spacer(1, 8),
                _table(["", ""], measures, [56 * mm, width - 56 * mm], style),
            ]
        ),
        *(
            [
                Spacer(1, 6),
                Paragraph(
                    verdict,
                    ParagraphStyle("verdict", parent=style["body"], textColor=ACCENT),
                ),
            ]
            if verdict
            else []
        ),
    ]


def _graded_periods(rows: list[dict[str, Any]]) -> list[tuple[date, float, float]]:
    """The run's own forecast periods that carry an actual, in calendar order."""
    graded = [
        (
            date.fromisoformat(str(row["period"])),
            float(row["forecast"]),
            float(row["actual"]),
        )
        for row in rows
        if row.get("series", TOP_LINE) == TOP_LINE
        and row.get("kind") == "forecast"
        and row.get("forecast") is not None
        and row.get("actual") is not None
    ]
    return sorted(graded, key=lambda graded_row: graded_row[0])


def _verdict(run: ForecastRun) -> str:
    """
    The one sentence a reader takes away, in the language of the fault.

    Bias and interval coverage are different failures needing different fixes,
    and neither is visible in the accuracy figure that sits above them.
    """
    parts: list[str] = []

    # Bias and wMAPE are both percentages of actual, so their ratio is exactly
    # the share of the error that points one way. Past a half the misses have
    # stopped cancelling, and the fix is a different one from "be more
    # accurate" — which is the only reason to say it out loud.
    bias, error = run.realized_bias, run.realized_wmape
    if bias is not None and error and abs(bias) >= error * DIRECTIONAL_SHARE:
        direction = "high" if bias > 0 else "low"
        parts.append(
            f"It ran {direction} by {abs(bias):.1f}% overall — with "
            f"{min(abs(bias) / error, 1.0) * 100:.0f}% of the error pointing the same way, this "
            "is a lean to correct rather than scatter to live with."
        )

    if intervals_held(run.realized_coverage, run.confidence_level) is False:
        parts.append(
            f"Actuals landed inside the {run.confidence_level * 100:.0f}% interval "
            f"{run.realized_coverage or 0.0:.0f}% of the time, so the interval was narrower "
            "than it claimed."
        )

    return " ".join(parts)


def _forecast_chart(
    rows: list[dict[str, Any]], run: ForecastRun, width: float, currency: bool
) -> ForecastChart | None:
    """
    The run's own history and horizon. Returns None where there is nothing to
    draw — a run with no history yet would otherwise render an empty frame.
    """
    top_line = [row for row in rows if row.get("series", TOP_LINE) == TOP_LINE]

    history = [
        (date.fromisoformat(str(row["period"])), float(row["actual"]))
        for row in top_line
        if row.get("kind") == "actual" and row.get("actual") is not None
    ]
    # Only the recent past. Three years of history behind a three-month horizon
    # squeezes the forecast into a sliver at the right-hand edge, and the
    # forecast is what the picture is for. Two comparison windows is what the
    # engine itself uses to judge seasonality — long enough to show the pattern
    # being extrapolated, derived from the frequency rather than picked.
    context = 2 * comparison_window(run.frequency, len(history))
    history = history[-context:] if len(history) > context else history

    horizon = [
        (date.fromisoformat(str(row["period"])), float(row["forecast"]))
        for row in top_line
        if row.get("kind") == "forecast" and row.get("forecast") is not None
    ]
    if len(history) + len(horizon) < 2:
        return None

    ahead = [row for row in top_line if row.get("kind") == "forecast"]
    lower = [float(row["lower_bound"]) for row in ahead if row.get("lower_bound") is not None]
    upper = [float(row["upper_bound"]) for row in ahead if row.get("upper_bound") is not None]
    complete = len(lower) == len(upper) == len(horizon)

    # What happened over the horizon, once it has been scored. Aligned with the
    # forecast period by period, with a hole where a period has not settled.
    realized = [
        None if row.get("actual") is None else float(row["actual"])
        for row in sorted(ahead, key=lambda row: str(row.get("period", "")))
    ]

    return ForecastChart(
        history=history,
        forecast=horizon,
        lower=lower if complete else [],
        upper=upper if complete else [],
        width=width,
        height=CHART_HEIGHT,
        currency=currency,
        realized=realized if any(value is not None for value in realized) else [],
    )


def _humanise(value: str | None) -> str:
    if not value:
        return "—"
    return value.replace("_", " ").replace(" pct", " %").strip().capitalize()
