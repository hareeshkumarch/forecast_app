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

TOP_LINE = "Total"

RISK_BARS = 12
CHART_HEIGHT = 52 * mm

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


WRAP_OVER = 24


def _number(value: Any, digits: int = 0) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _magnitude(value: Any) -> str:
    """A number formatted to the precision its own size deserves.

    Driver impacts are in the target's units, and the target can be revenue in
    the millions or a conversion rate under one. Rounding everything to whole
    numbers rendered every small driver as "0" — a column of zeroes that
    silently claimed nothing was moving anything.
    """
    if value is None:
        return "—"
    try:
        magnitude = abs(float(value))
    except (TypeError, ValueError):
        return str(value)
    if magnitude >= 100:
        return _number(value, 0)
    if magnitude >= 1:
        return _number(value, 1)
    return _number(value, 3)


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

    chart = _forecast_chart(rows, run, width, currency)
    if chart is not None:
        story.append(Paragraph("THE FORECAST", style["section"]))
        story.append(
            Paragraph(
                f"History to {_when(run.history_end)}, then {run.horizon} "
                f"{'period' if run.horizon == 1 else 'periods'} ahead. The band is the "
                f"{run.confidence_level * 100:.0f}% interval: the forecast is one line "
                "through it, not a promise.",
                style["body"],
            )
        )
        story.append(Spacer(1, 5))
        story.append(chart)
        story.append(Spacer(1, 10))
    story.extend(_scorecard_section(run, rows, width, currency, style))

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
                ]
            )
        )
        if len(series) > RISK_BARS:
            story.append(Spacer(1, 5))
            story.append(
                Paragraph(
                    f"The {RISK_BARS} largest of {len(series):,} series. Every series, with "
                    "its forecast and measured error, is in the CSV and Excel exports.",
                    style["body"],
                )
            )

    drivers = sheets.get("drivers") or []
    if drivers:
        story.append(
            KeepTogether(
                [
                    Paragraph("WHAT IS MOVING IT", style["section"]),
                    Paragraph(
                        "Each driver's share of the movement this forecast explains, in "
                        "the measure's own units. Shares are relative to one another, not "
                        "to the total.",
                        style["body"],
                    ),
                    Spacer(1, 6),
                    _table(
                        ["Driver", "Impact", "Share", "Direction"],
                        [
                            [
                                str(row.get("driver", "")),
                                _magnitude(row.get("impact")),
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

    story.extend(_method_section(run, unit, width, style))

    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "<b>Where the numbers are.</b> This report is the picture. Every period, every "
            "series and every breakdown — with lower and upper bounds, best and worst case — "
            "is in the CSV and Excel exports of this same run, which are built to be opened "
            "in a spreadsheet rather than read on a page.",
            style["body"],
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


def _method_section(
    run: ForecastRun,
    unit: str,
    width: float,
    style: dict[str, ParagraphStyle],
) -> list[Any]:
    """What the reader needs to know before trusting any of the above.

    Last rather than first, deliberately. It is reference material: the reader
    came for the forecast, and reaches this when they want to know what
    produced it. Leading with eleven rows of configuration buries the answer.
    """
    out: list[Any] = [Paragraph("HOW THIS FORECAST WAS MADE", style["section"])]
    grain = ", ".join(run.group_by) if run.group_by else "one total series"
    out.append(
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
        out.append(Spacer(1, 6))
        out.append(
            Paragraph(
                f"<b>Read with care.</b> {run.fallback_reason}",
                ParagraphStyle("warn", parent=style["body"], textColor=ACCENT),
            )
        )
    return out


def _scorecard_section(
    run: ForecastRun,
    rows: list[dict[str, Any]],
    width: float,
    currency: bool,
    style: dict[str, ParagraphStyle],
) -> list[Any]:
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
    parts: list[str] = []

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
    top_line = [row for row in rows if row.get("series", TOP_LINE) == TOP_LINE]

    history = [
        (date.fromisoformat(str(row["period"])), float(row["actual"]))
        for row in top_line
        if row.get("kind") == "actual" and row.get("actual") is not None
    ]
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
