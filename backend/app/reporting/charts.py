from __future__ import annotations

from datetime import date
from typing import Any

from reportlab.lib.units import mm
from reportlab.platypus import Flowable

from app.reporting.palette import (
    ACCENT,
    BAND_FILL,
    COMMIT,
    FAINT,
    GRID,
    INK,
    MUTED,
    PLAN_FILL,
    POSITIVE,
    PREPARE,
    RISK_REST,
)

GRID_LINES = 4
MIN_BAND_HEIGHT = 0.4


# Quarters cleanly under a four-line grid. One significant digit is too coarse
# near a power of ten: 1.01M rounds to 2M and the chart loses half its height.
NICE_STEPS = (1.0, 1.2, 1.6, 2.0, 2.4, 3.2, 4.0, 5.0, 6.0, 8.0, 10.0)
STEP_SLACK = 1e-9


def _nice_ceiling(value: float) -> float:
    if value <= 0:
        return 1.0

    from math import floor, log10

    magnitude = 10.0 ** floor(log10(value))
    scaled = value / magnitude

    for step in NICE_STEPS:
        if scaled <= step + STEP_SLACK:
            return step * magnitude
    return 10.0 * magnitude


def _compact(value: float, currency: bool) -> str:
    prefix = "$" if currency else ""
    sign = "-" if value < 0 else ""
    size = abs(value)

    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if size >= limit:
            return f"{sign}{prefix}{size / limit:.1f}{suffix}"
    return f"{sign}{prefix}{size:,.0f}"


class ForecastChart(Flowable):
    def __init__(
        self,
        history: list[tuple[date, float]],
        forecast: list[tuple[date, float]],
        lower: list[float],
        upper: list[float],
        width: float,
        height: float,
        currency: bool = True,
        realized: list[float | None] | None = None,
    ) -> None:
        super().__init__()
        self.history = history
        self.forecast = forecast
        self.lower = lower
        self.upper = upper
        self.width = width
        self.height = height
        self.currency = currency
        self.realized = realized or []

    def wrap(self, *_args: Any) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        values = [value for _, value in self.history] + [value for _, value in self.forecast]
        if not values:
            return

        pad_left, pad_bottom, pad_top = 22 * mm, 8 * mm, 4 * mm
        plot_width = self.width - pad_left
        plot_height = self.height - pad_bottom - pad_top

        band = [v for v in (*self.lower, *self.upper) if v is not None]
        settled = [v for v in self.realized if v is not None]
        ceiling = _nice_ceiling(max([*values, *band, *settled]))
        floor = min([*values, *band, *settled, 0.0])
        span = ceiling - floor or 1.0

        count = len(values)
        step = plot_width / max(count - 1, 1)

        def x(index: int) -> float:
            return pad_left + index * step

        def y(value: float) -> float:
            return pad_bottom + (value - floor) / span * plot_height

        canvas.setFont("Helvetica", 6.5)
        for line in range(GRID_LINES + 1):
            value = floor + span * line / GRID_LINES
            at = y(value)
            canvas.setStrokeColor(GRID)
            canvas.setLineWidth(0.4)
            canvas.line(pad_left, at, self.width, at)
            canvas.setFillColor(FAINT)
            canvas.drawRightString(pad_left - 2 * mm, at - 1.6, _compact(value, self.currency))

        split = len(self.history)
        if self.lower and self.upper and len(self.lower) == len(self.forecast):
            path = canvas.beginPath()
            anchor = split - 1 if split else 0
            path.moveTo(x(anchor), y(values[anchor]))
            for index, value in enumerate(self.upper):
                path.lineTo(x(split + index), y(value))
            for index in range(len(self.lower) - 1, -1, -1):
                path.lineTo(x(split + index), y(self.lower[index]))
            path.lineTo(x(anchor), y(values[anchor]))
            path.close()

            if plot_height * (max(self.upper) - min(self.lower)) / span > MIN_BAND_HEIGHT:
                canvas.setFillColor(BAND_FILL)
                canvas.drawPath(path, stroke=0, fill=1)

        if split and split < count:
            canvas.setStrokeColor(MUTED)
            canvas.setLineWidth(0.5)
            canvas.setDash(2, 2)
            canvas.line(x(split - 1), pad_bottom, x(split - 1), pad_bottom + plot_height)
            canvas.setDash()

            canvas.setFont("Helvetica", 6.5)
            canvas.setFillColor(MUTED)
            canvas.drawString(x(split - 1) + 1.5 * mm, pad_bottom + plot_height - 3, "Forecast")

        canvas.setLineWidth(1.1)
        canvas.setStrokeColor(INK)
        self._polyline(canvas, x, y, values[:split], 0)

        canvas.setStrokeColor(ACCENT)
        canvas.setDash(3, 2)
        self._polyline(canvas, x, y, values[max(split - 1, 0) :], max(split - 1, 0))
        canvas.setDash()

        graded = [
            (split + index, value)
            for index, value in enumerate(self.realized)
            if value is not None and split + index < count
        ]
        if graded:
            canvas.setStrokeColor(POSITIVE)
            canvas.setLineWidth(1.3)
            path = canvas.beginPath()
            path.moveTo(x(graded[0][0]), y(graded[0][1]))
            for index, value in graded[1:]:
                path.lineTo(x(index), y(value))
            canvas.drawPath(path, stroke=1, fill=0)

            canvas.setFillColor(POSITIVE)
            for index, value in graded:
                canvas.circle(x(index), y(value), 1.5, stroke=0, fill=1)

            canvas.setFont("Helvetica", 6.5)
            canvas.drawRightString(self.width, pad_bottom + plot_height + 1.5 * mm, "Actual")

        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(FAINT)
        if self.history:
            canvas.drawString(pad_left, 2 * mm, self.history[0][0].isoformat())
        if self.forecast:
            canvas.drawRightString(self.width, 2 * mm, self.forecast[-1][0].isoformat())

    @staticmethod
    def _polyline(canvas: Any, x: Any, y: Any, series: list[float], offset: int) -> None:
        if len(series) < 2:
            return
        path = canvas.beginPath()
        path.moveTo(x(offset), y(series[0]))
        for index, value in enumerate(series[1:], start=1):
            path.lineTo(x(offset + index), y(value))
        canvas.drawPath(path, stroke=1, fill=0)


class RiskChart(Flowable):
    def __init__(
        self,
        rows: list[tuple[str, float]],
        width: float,
        height: float,
        currency: bool = True,
        cut: int | None = None,
    ) -> None:
        super().__init__()
        self.rows = rows
        self.width = width
        self.height = height
        self.currency = currency
        self.cut = cut

    def wrap(self, *_args: Any) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        if not self.rows:
            return

        largest = max(value for _, value in self.rows) or 1.0
        label_width = 46 * mm
        value_width = 20 * mm
        track = self.width - label_width - value_width

        gap = self.height / len(self.rows)
        bar = min(gap * 0.6, 5 * mm)
        cut = self.cut if self.cut and 0 < self.cut < len(self.rows) else None

        for index, (label, value) in enumerate(self.rows):
            top = self.height - (index + 1) * gap + (gap - bar) / 2
            leading = cut is not None and index < cut

            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(INK if leading or cut is None else MUTED)
            canvas.drawString(0, top + bar / 2 - 2.2, _clip(label, 34))

            canvas.setFillColor(ACCENT if leading or cut is None else RISK_REST)
            canvas.rect(label_width, top, max(track * value / largest, 0.4), bar, stroke=0, fill=1)

            canvas.setFillColor(MUTED)
            canvas.drawRightString(self.width, top + bar / 2 - 2.2, _compact(value, self.currency))

        if cut is None:
            return

        at = self.height - cut * gap

        # Rows leave ~7pt between bars, which a 6pt caption clears at neither
        # end; on the rule, in the gutter between value labels, it has room.
        canvas.setFont("Helvetica-Bold", 6)
        caption = "HALF THE RISK IS ABOVE THIS LINE"
        caption_width = canvas.stringWidth(caption, "Helvetica-Bold", 6)

        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(0.6)
        canvas.setDash(2, 2)
        canvas.line(label_width, at, self.width - caption_width - 2 * mm, at)
        canvas.setDash()

        canvas.setFillColor(ACCENT)
        canvas.drawRightString(self.width, at - 2.0, caption)


class ScoreChart(Flowable):
    def __init__(
        self,
        rows: list[tuple[date, float, float]],
        width: float,
        height: float,
        currency: bool = True,
    ) -> None:
        super().__init__()
        self.rows = rows
        self.width = width
        self.height = height
        self.currency = currency

    def wrap(self, *_args: Any) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        if not self.rows:
            return

        pad_left, pad_bottom, pad_top = 22 * mm, 9 * mm, 5 * mm
        plot_width = self.width - pad_left
        plot_height = self.height - pad_bottom - pad_top
        if plot_height <= 0 or plot_width <= 0:
            return

        values = [value for _, forecast, actual in self.rows for value in (forecast, actual)]
        ceiling = _nice_ceiling(max(values)) or 1.0
        floor = min([*values, 0.0])
        span = ceiling - floor or 1.0

        def y(value: float) -> float:
            return pad_bottom + (value - floor) / span * plot_height

        canvas.setFont("Helvetica", 6.5)
        for line in range(GRID_LINES + 1):
            value = floor + span * line / GRID_LINES
            at = y(value)
            canvas.setStrokeColor(GRID)
            canvas.setLineWidth(0.4)
            canvas.line(pad_left, at, self.width, at)
            canvas.setFillColor(FAINT)
            canvas.drawRightString(pad_left - 2 * mm, at - 1.6, _compact(value, self.currency))

        slot = plot_width / len(self.rows)
        bar = min(slot * 0.32, 9 * mm)
        base = y(max(floor, 0.0))

        for index, (period, forecast, actual) in enumerate(self.rows):
            centre = pad_left + (index + 0.5) * slot

            for offset, value, colour in (
                (-bar, forecast, ACCENT),
                (0.0, actual, POSITIVE),
            ):
                top = y(value)
                canvas.setFillColor(colour)
                canvas.rect(
                    centre + offset,
                    min(base, top),
                    bar,
                    max(abs(top - base), MIN_BAND_HEIGHT),
                    stroke=0,
                    fill=1,
                )

            canvas.setFont("Helvetica", 6.5)
            canvas.setFillColor(FAINT)
            canvas.drawCentredString(centre, 3.5 * mm, period.isoformat())

        canvas.setFont("Helvetica", 6.5)
        for offset, label, colour in ((0.0, "Forecast", ACCENT), (18 * mm, "Actual", POSITIVE)):
            canvas.setFillColor(colour)
            canvas.rect(pad_left + offset, self.height - 3 * mm, 3 * mm, 2.4, stroke=0, fill=1)
            canvas.setFillColor(MUTED)
            canvas.drawString(pad_left + offset + 4.5 * mm, self.height - 3 * mm, label)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


class PlanBand(Flowable):
    LABELS = ("COMMIT TO", "BASE CASE", "BE READY FOR")

    def __init__(
        self,
        commit: float,
        base: float,
        prepare: float,
        width: float,
        height: float,
        currency: bool = True,
    ) -> None:
        super().__init__()
        self.commit = commit
        self.base = base
        self.prepare = prepare
        self.width = width
        self.height = height
        self.currency = currency

    def wrap(self, *_args: Any) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        span = self.prepare - self.commit
        left, right = 2 * mm, self.width - 2 * mm
        track = right - left
        bar_height = 7 * mm
        bar_bottom = 9 * mm

        def x(value: float) -> float:
            if span <= 0:
                return left + track / 2
            return left + (value - self.commit) / span * track

        canvas.setFillColor(PLAN_FILL)
        canvas.rect(left, bar_bottom, track, bar_height, stroke=0, fill=1)

        for value, colour in ((self.commit, COMMIT), (self.prepare, PREPARE)):
            canvas.setFillColor(colour)
            canvas.rect(x(value) - 0.75, bar_bottom, 1.5, bar_height, stroke=0, fill=1)

        base_at = x(self.base)
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(1.2)
        canvas.line(base_at, bar_bottom - 1.5 * mm, base_at, bar_bottom + bar_height + 1.5 * mm)

        values = (self.commit, self.base, self.prepare)
        colours = (COMMIT, INK, PREPARE)
        top = bar_bottom + bar_height + 3.5 * mm

        for index, (label, value, colour) in enumerate(
            zip(self.LABELS, values, colours, strict=True)
        ):
            at = x(value)
            canvas.setFont("Helvetica", 6.5)
            canvas.setFillColor(FAINT)
            _anchored(canvas, at, top + 5 * mm, label, index, left, right)

            canvas.setFont("Helvetica-Bold", 10.5)
            canvas.setFillColor(colour)
            _anchored(canvas, at, top, _compact(value, self.currency), index, left, right)


def _anchored(
    canvas: Any, at: float, y: float, text: str, index: int, left: float, right: float
) -> None:
    if index == 0:
        canvas.drawString(left, y, text)
    elif index == 2:
        canvas.drawRightString(right, y, text)
    else:
        half = canvas.stringWidth(text, canvas._fontname, canvas._fontsize) / 2
        canvas.drawCentredString(min(max(at, left + half), right - half), y, text)
