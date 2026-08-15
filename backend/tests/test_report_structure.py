"""What the PDF is for.

The report is the picture; the CSV and Excel exports are the numbers. These
assert that split holds — that every drawn thing is introduced by a heading,
and that the row-by-row tables which belong in a spreadsheet have not crept
back onto the page.

The charts themselves are covered by test_report_charts.py. This is about the
document they sit in.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.enums import ForecastFrequency, GapFill, MeasureAggregation
from app.reporting import pdf

pdfplumber = pytest.importorskip("pdfplumber")

MONTHLY = ForecastFrequency.MONTHLY


def _run(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "name": "Q3 demand",
        "frequency": MONTHLY,
        "horizon": 6,
        "target_column": "revenue",
        "selected_model": SimpleNamespace(value="ensemble"),
        "selection_rationale": "Best wMAPE over five folds.",
        "confidence_level": 0.95,
        "series_count": 42,
        "group_by": ["region"],
        "region_column": "region",
        "category_column": "category",
        "aggregation": MeasureAggregation.SUM,
        "gap_fill": GapFill.ZERO,
        "leading_columns": [{"name": "promo_spend", "lag": 2}],
        "used_fallback": False,
        "fallback_reason": None,
        "history_start": date(2023, 1, 1),
        "history_end": date(2025, 12, 1),
        "forecast_start": date(2026, 1, 1),
        "forecast_end": date(2026, 6, 1),
        "realized_wmape": 12.4,
        "realized_bias": -2.1,
        "realized_mae": 880.0,
        "realized_coverage": 91.7,
        "scored_periods": 3,
        "scored_at": datetime(2026, 7, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "period": date(2023 + i // 12, i % 12 + 1, 1),
            "kind": "actual",
            "actual": 1000 + i * 30,
            "forecast": 990 + i * 30,
        }
        for i in range(36)
    ]
    rows += [
        {
            "period": date(2026, i + 1, 1),
            "kind": "forecast",
            "forecast": 2100 + i * 40,
            "lower_bound": 1950 + i * 40,
            "upper_bound": 2260 + i * 40,
            "best_case": 2300 + i * 40,
            "worst_case": 1900 + i * 40,
            "actual": (2080 + i * 40) if i < 3 else None,
        }
        for i in range(6)
    ]
    return rows


def _sheets(*, driver_impact: float = 4200.0) -> dict[str, list[dict[str, Any]]]:
    return {
        "metrics": [
            {"name": "wmape", "value": 11.2, "unit": "percent", "previous_value": 13.0},
        ],
        "series": [
            {
                "series": f"SKU-{i:03d}",
                "forecast": 40000 - i * 500,
                "value_at_risk": 90000 - i * 3000,
                "wmape_pct": 30 - i,
                "measured": True,
            }
            for i in range(28)
        ],
        "drivers": [
            {
                "driver": "promo_spend",
                "impact": driver_impact,
                "impact_pct": 42.0,
                "direction": "up",
            }
        ],
        "regions": [{"region": "North", "forecast": 5000}],
        "categories": [{"category": "Grocery", "forecast": 5000}],
    }


def _text(tmp_path: Path, **kwargs: Any) -> str:
    out = tmp_path / "report.pdf"
    pdf.build(out, _run(), _rows(), _sheets(**kwargs), max_rows=200)
    with pdfplumber.open(out) as document:
        return "\n".join((page.extract_text() or "") for page in document.pages)


# ------------------------------------------------------- every drawing is named


@pytest.mark.parametrize(
    "heading",
    [
        "THE FORECAST",
        "HOW THIS FORECAST ACTUALLY DID",
        "SERIES AT RISK",
        "WHAT IS MOVING IT",
        "HOW THIS FORECAST WAS MADE",
    ],
)
def test_each_section_announces_itself(tmp_path: Path, heading: str) -> None:
    # A chart with no heading is a picture the reader has to identify from its
    # axes. The forecast chart used to open the document unlabelled.
    assert heading in _text(tmp_path)


def test_the_forecast_chart_is_introduced_before_it_is_drawn(tmp_path: Path) -> None:
    text = _text(tmp_path)
    assert text.index("THE FORECAST") < text.index("HOW THIS FORECAST ACTUALLY DID")
    # And the caption says what the band is, since a shaded region is not
    # self-explanatory.
    assert "95% interval" in text


# ------------------------------------------------- numbers belong in the export


def test_the_row_by_row_horizon_table_is_not_in_the_pdf(tmp_path: Path) -> None:
    # One row per period, six columns wide, is a spreadsheet. It was two pages
    # of the old report and is the whole content of the CSV export.
    text = _text(tmp_path)
    assert "Best case Worst case" not in text


def test_the_reader_is_told_where_the_numbers_are(tmp_path: Path) -> None:
    text = _text(tmp_path)
    assert "CSV and Excel exports" in text


def test_the_risk_section_draws_bars_rather_than_listing_every_series(
    tmp_path: Path,
) -> None:
    text = _text(tmp_path)
    # 28 series in, at most RISK_BARS drawn, and no table of the rest.
    assert "SKU-000" in text
    assert f"SKU-{pdf.RISK_BARS:03d}" not in text
    assert "largest of 28 series" in text


# ---------------------------------------------------- a number that means what


def test_a_small_driver_impact_does_not_render_as_zero(tmp_path: Path) -> None:
    # Impacts are in the target's units, and a conversion rate or a margin sits
    # below one. Fixed zero-decimal formatting turned every such driver into
    # "0" — a column claiming nothing moved anything.
    text = _text(tmp_path, driver_impact=0.42)
    assert "0.420" in text


def test_a_large_driver_impact_stays_readable(tmp_path: Path) -> None:
    text = _text(tmp_path, driver_impact=4200.0)
    assert "4,200" in text


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.42, "0.420"), (4.2, "4.2"), (4200.0, "4,200"), (None, "—"), ("n/a", "n/a")],
)
def test_magnitude_picks_precision_from_size(value: Any, expected: str) -> None:
    assert pdf._magnitude(value) == expected
