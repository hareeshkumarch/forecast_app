from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from app.forecasting.availability import prophet_availability
from app.forecasting.engine import ForecastInput, SeriesInput, run_forecast
from app.forecasting.metrics import coverage, mase, wmape
from app.models.enums import ForecastFrequency

SEED = 20260912
CONFIDENCE_LEVEL = 0.8

SEASONAL_PERIOD = {
    ForecastFrequency.DAILY: 7,
    ForecastFrequency.WEEKLY: 52,
    ForecastFrequency.MONTHLY: 12,
    ForecastFrequency.QUARTERLY: 4,
}

_STEP = {
    ForecastFrequency.DAILY: timedelta(days=1),
    ForecastFrequency.WEEKLY: timedelta(weeks=1),
}


@dataclass(slots=True)
class Shape:
    name: str
    frequency: ForecastFrequency
    horizon: int
    values: list[float]


@dataclass(slots=True)
class Scored:
    name: str
    model: str
    wmape_pct: float
    mase: float
    coverage_pct: float


def _periods(n: int, frequency: ForecastFrequency) -> list[date]:
    start = date(2022, 1, 3)
    step = _STEP.get(frequency)
    if step is not None:
        return [start + step * i for i in range(n)]
    if frequency is ForecastFrequency.MONTHLY:
        return [date(2022 + (i // 12), (i % 12) + 1, 1) for i in range(n)]
    return [date(2022 + (i // 4), ((i % 4) * 3) + 1, 1) for i in range(n)]


def shapes() -> list[Shape]:
    rng = np.random.default_rng(SEED)
    out: list[Shape] = []

    n = 156
    t = np.arange(n, dtype=float)
    season = 12 * np.sin(2 * np.pi * t / 52.0)

    out.append(
        Shape(
            "weekly-trend", ForecastFrequency.WEEKLY, 13, list(100 + 0.8 * t + rng.normal(0, 4, n))
        )
    )
    out.append(
        Shape(
            "weekly-seasonal",
            ForecastFrequency.WEEKLY,
            13,
            list(200 + season + rng.normal(0, 5, n)),
        )
    )
    out.append(
        Shape(
            "weekly-trend-seasonal",
            ForecastFrequency.WEEKLY,
            13,
            list(150 + 0.5 * t + season + rng.normal(0, 5, n)),
        )
    )
    out.append(
        Shape(
            "weekly-level-shift",
            ForecastFrequency.WEEKLY,
            13,
            list(np.where(t < 100, 80.0, 130.0) + rng.normal(0, 4, n)),
        )
    )
    out.append(
        Shape("weekly-flat-noisy", ForecastFrequency.WEEKLY, 13, list(500 + rng.normal(0, 25, n)))
    )
    out.append(
        Shape(
            "weekly-exponential",
            ForecastFrequency.WEEKLY,
            13,
            list(50 * np.exp(0.012 * t) * (1 + rng.normal(0, 0.05, n))),
        )
    )

    lumpy = rng.poisson(3.0, n).astype(float)
    lumpy[rng.random(n) < 0.55] = 0.0
    out.append(Shape("weekly-intermittent", ForecastFrequency.WEEKLY, 13, list(lumpy)))

    spiky = 100 + rng.normal(0, 6, n)
    spiky[::13] += 90
    out.append(Shape("weekly-spiky", ForecastFrequency.WEEKLY, 13, list(spiky)))

    m = 60
    tm = np.arange(m, dtype=float)
    out.append(
        Shape(
            "monthly-trend-seasonal",
            ForecastFrequency.MONTHLY,
            6,
            list(1000 + 8 * tm + 120 * np.sin(2 * np.pi * tm / 12.0) + rng.normal(0, 30, m)),
        )
    )

    d = 730
    td = np.arange(d, dtype=float)
    out.append(
        Shape(
            "daily-weekly-cycle",
            ForecastFrequency.DAILY,
            28,
            list(60 + 0.02 * td + 15 * np.sin(2 * np.pi * td / 7.0) + rng.normal(0, 3, d)),
        )
    )

    return out


def score(shape: Shape) -> tuple[Scored, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(shape.values)
    h = shape.horizon
    train = np.asarray(shape.values[: n - h], dtype=float)
    held = np.asarray(shape.values[n - h :], dtype=float)
    periods = _periods(n, shape.frequency)

    result = run_forecast(
        ForecastInput(
            series=SeriesInput(periods=periods[: n - h], values=list(train)),
            frequency=shape.frequency,
            horizon=h,
            confidence_level=CONFIDENCE_LEVEL,
        )
    )

    pred = np.asarray(result.point_forecast[:h], dtype=float)
    lower = np.asarray(result.lower_bound[:h], dtype=float)
    upper = np.asarray(result.upper_bound[:h], dtype=float)

    scored = Scored(
        name=shape.name,
        model=str(result.selected_model),
        wmape_pct=wmape(held, pred),
        mase=mase(held, pred, train, seasonal_period=SEASONAL_PERIOD[shape.frequency]),
        coverage_pct=coverage(held, lower, upper),
    )
    return scored, held, pred, lower, upper


def run() -> dict[str, object]:
    rows: list[Scored] = []
    held_all: list[float] = []
    pred_all: list[float] = []
    lower_all: list[float] = []
    upper_all: list[float] = []

    for shape in shapes():
        scored, held, pred, lower, upper = score(shape)
        rows.append(scored)
        held_all.extend(held.tolist())
        pred_all.extend(pred.tolist())
        lower_all.extend(lower.tolist())
        upper_all.extend(upper.tolist())

    held_arr = np.asarray(held_all)
    pred_arr = np.asarray(pred_all)
    finite_mase = [r.mase for r in rows if np.isfinite(r.mase)]

    return {
        "seed": SEED,
        "confidence_level": CONFIDENCE_LEVEL,
        "prophet_available": prophet_availability().available,
        "shapes": [
            {
                "name": r.name,
                "model": r.model,
                "wmape_pct": round(r.wmape_pct, 4),
                "mase": round(r.mase, 4),
                "coverage_pct": round(r.coverage_pct, 4),
            }
            for r in rows
        ],
        "pooled": {
            "wmape_pct": round(wmape(held_arr, pred_arr), 4),
            "mase_mean": round(float(np.mean(finite_mase)), 4),
            "coverage_pct": round(
                coverage(held_arr, np.asarray(lower_all), np.asarray(upper_all)), 4
            ),
            "nominal_coverage_pct": CONFIDENCE_LEVEL * 100.0,
        },
    }


def _render(report: dict[str, object]) -> str:
    pooled = report["pooled"]
    assert isinstance(pooled, dict)
    lines = [
        f"seed {report['seed']}   confidence {report['confidence_level']}   "
        f"prophet {'available' if report['prophet_available'] else 'UNAVAILABLE'}",
        "",
        f"{'shape':26} {'model':18} {'wMAPE %':>9} {'MASE':>8} {'cover %':>9}",
    ]
    shapes_report = report["shapes"]
    assert isinstance(shapes_report, list)
    for row in shapes_report:
        lines.append(
            f"{row['name']:26} {row['model']:18} "
            f"{row['wmape_pct']:9.2f} {row['mase']:8.3f} {row['coverage_pct']:9.1f}"
        )
    lines += [
        "",
        f"pooled wMAPE    {pooled['wmape_pct']:.4f} %",
        f"mean   MASE     {pooled['mase_mean']:.4f}",
        f"pooled coverage {pooled['coverage_pct']:.4f} %   nominal {pooled['nominal_coverage_pct']:.1f} %",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure held-out accuracy over ten fixed series shapes. "
            "Every figure is a percentage where its name says so."
        )
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args()

    report = run()
    print(json.dumps(report, indent=2) if args.json else _render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
