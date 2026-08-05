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
from app.models.entities import ForecastRun
from app.reporting.charts import ForecastChart, RiskChart
from app.reporting.palette import ACCENT, BAND, FAINT, INK, MUTED, RULE

#: Matches `exporter.TOP_LINE` — a point that belongs to the run, not a series.
TOP_LINE = "Total"

#: Bars in the risk chart. Past this the picture stops being scannable and the
#: table underneath is the better way to read the tail.
RISK_BARS = 12
CHART_HEIGHT = 52 * mm

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
    chart = _forecast_chart(rows, width, currency)
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

    # ---- how well it has done
    metrics = sheets.get("metrics") or []
    if metrics:
        story.append(Paragraph("MEASURED ACCURACY", style["section"]))
        story.append(
            Paragraph(
                "Every figure below comes from backtesting: the model was refitted on earlier "
                "windows and scored against periods it had not seen.",
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


def _forecast_chart(
    rows: list[dict[str, Any]], width: float, currency: bool
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
    horizon = [
        (date.fromisoformat(str(row["period"])), float(row["forecast"]))
        for row in top_line
        if row.get("kind") == "forecast" and row.get("forecast") is not None
    ]
    if len(history) + len(horizon) < 2:
        return None

    bounds = [
        (row.get("lower_bound"), row.get("upper_bound"))
        for row in top_line
        if row.get("kind") == "forecast"
    ]
    lower = [float(low) for low, _ in bounds if low is not None]
    upper = [float(high) for _, high in bounds if high is not None]
    complete = len(lower) == len(upper) == len(horizon)

    return ForecastChart(
        history=history,
        forecast=horizon,
        lower=lower if complete else [],
        upper=upper if complete else [],
        width=width,
        height=CHART_HEIGHT,
        currency=currency,
    )


def _humanise(value: str | None) -> str:
    if not value:
        return "—"
    return value.replace("_", " ").replace(" pct", " %").strip().capitalize()
