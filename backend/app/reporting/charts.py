from __future__ import annotations

from datetime import date
from typing import Any

from reportlab.lib.units import mm
from reportlab.platypus import Flowable

from app.reporting.palette import ACCENT, BAND_FILL, FAINT, GRID, INK, MUTED, POSITIVE

GRID_LINES = 4
MIN_BAND_HEIGHT = 0.4


def _nice_ceiling(value: float) -> float:
    if value <= 0:
        return 1.0

    from math import ceil, floor, log10

    magnitude = 10.0 ** floor(log10(value))
    return float(ceil(value / magnitude) * magnitude)


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

        largest = max(value for _, value in self.rows) or 1.0
        label_width = 46 * mm
        value_width = 20 * mm
        track = self.width - label_width - value_width

        gap = self.height / len(self.rows)
        bar = min(gap * 0.6, 5 * mm)

        for index, (label, value) in enumerate(self.rows):
            top = self.height - (index + 1) * gap + (gap - bar) / 2

            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(INK)
            canvas.drawString(0, top + bar / 2 - 2.2, _clip(label, 34))

            canvas.setFillColor(ACCENT if index == 0 else POSITIVE)
            canvas.rect(label_width, top, max(track * value / largest, 0.4), bar, stroke=0, fill=1)

            canvas.setFillColor(MUTED)
            canvas.drawRightString(self.width, top + bar / 2 - 2.2, _compact(value, self.currency))


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
