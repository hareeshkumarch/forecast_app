
from __future__ import annotations

import csv
import io
from datetime import date

import numpy as np

from app.forecasting.frequency import add_periods
from app.models.enums import ForecastFrequency

SEED = 20260804

REGIONS: dict[str, float] = {
    "North America": 0.42,
    "Europe": 0.25,
    "Asia Pacific": 0.18,
    "Latin America": 0.09,
    "Middle East & Africa": 0.06,
}

CATEGORIES: dict[str, float] = {
    "Product A": 0.35,
    "Product B": 0.26,
    "Product C": 0.18,
    "Product D": 0.12,
    "Others": 0.09,
}

                                                                              
REGION_GROWTH: dict[str, float] = {
    "North America": 0.11,
    "Europe": 0.05,
    "Asia Pacific": 0.24,
    "Latin America": 0.07,
    "Middle East & Africa": 0.03,
}

                                                                           
CATEGORY_GROWTH: dict[str, float] = {
    "Product A": 0.14,
    "Product B": 0.06,
    "Product C": -0.09,
    "Product D": 0.19,
    "Others": 0.04,
}

MONTHS = 42
START = date(2022, 7, 1)
BASE_MONTHLY_REVENUE = 1_950_000.0
AVERAGE_UNIT_PRICE = 48.0

HEADERS = ("order_date", "region", "product_category", "revenue", "units_sold")


def generate_rows() -> list[dict[str, object]]:
    rng = np.random.default_rng(SEED)
    rows: list[dict[str, object]] = []

    for index in range(MONTHS):
        period = add_periods(START, index, ForecastFrequency.MONTHLY)
        years_elapsed = index / 12.0

                                                         
        seasonal = 1.0 + 0.09 * np.sin(2 * np.pi * (index - 2) / 12.0)

        for region, region_share in REGIONS.items():
            region_factor = (1.0 + REGION_GROWTH[region]) ** years_elapsed

            for category, category_share in CATEGORIES.items():
                category_factor = (1.0 + CATEGORY_GROWTH[category]) ** years_elapsed

                revenue = (
                    BASE_MONTHLY_REVENUE
                    * region_share
                    * category_share
                    * region_factor
                    * category_factor
                    * seasonal
                    * (1.0 + rng.normal(0.0, 0.045))
                )

                                                                          
                if index == MONTHS - 4 and category in ("Product A", "Product B"):
                    revenue *= 1.34

                unit_price = AVERAGE_UNIT_PRICE * (1.0 + 0.03 * years_elapsed) * (
                    1.0 + rng.normal(0.0, 0.02)
                )
                units = max(1, int(round(revenue / unit_price)))

                rows.append(
                    {
                        "order_date": period.isoformat(),
                        "region": region,
                        "product_category": category,
                        "revenue": round(float(revenue), 2),
                        "units_sold": units,
                    }
                )

    return rows


def generate_csv() -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(HEADERS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(generate_rows())  # type: ignore[arg-type]
    return buffer.getvalue()


def generate_csv_bytes() -> bytes:
    return generate_csv().encode("utf-8")


if __name__ == "__main__":  # pragma: no cover - manual regeneration helper
    import sys

    sys.stdout.write(generate_csv())
