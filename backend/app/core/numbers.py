"""
The boundary between a number numpy is happy with and one a row can hold.

Inside the forecasting layer, NaN and ±Infinity are ordinary and useful: they
are how "this could not be measured" and "this diverged" are carried through an
array. Outside it they are neither storable nor sendable — Postgres rejects
them in a JSON column, and `json.dumps` refuses them outright, which turns a
series the platform merely could not measure into a failed run or a 500.

So they stop here. Not measurable becomes absent, which is the same statement
and one every reader already knows how to render.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, overload


@overload
def finite(value: None) -> None: ...


@overload
def finite(value: float | int) -> float | None: ...


def finite(value: Any) -> float | None:
    """The value as a storable float, or None when it is not one."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def storable(payload: Any) -> Any:
    """
    The same rule applied through a blob on its way to a JSON column.

    Model parameters carry whatever the fitting library reported — a Holt-Winters
    fit on a flat series reports an AICc of -Infinity, quite correctly — and one
    of those anywhere in the dict fails the whole insert with a Postgres syntax
    error naming a token nobody wrote.
    """
    if isinstance(payload, dict):
        return {key: storable(value) for key, value in payload.items()}
    if isinstance(payload, list | tuple):
        return [storable(item) for item in payload]
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, float | int):
        return finite(payload)
    return payload


#: Where each suffix takes over. Ordered largest first so the first match wins.
SCALES: tuple[tuple[float, str], ...] = (
    (1e12, "T"),
    (1e9, "B"),
    (1e6, "M"),
    (1e3, "K"),
)

#: Below this a decimal reads as a wall of zeros and an exponent is kinder.
EXPONENT_BELOW = 1e-4

#: How many digits of a sub-unit value actually carry information. Three is
#: what a conversion rate or a defect rate is quoted to.
SIGNIFICANT = 3


def _round(value: float, places: int) -> str:
    """
    Half away from zero, which is what everyone outside a numerics library
    means by rounding — Python's default sends 1.25 down to 1.2 and JavaScript
    sends it up to 1.3, so the same figure read 1.2K on the card and 1.3K in
    the report of the same run.
    """
    try:
        quantum = Decimal(1).scaleb(-places)
        return str(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return f"{value:.{places}f}"


def compact(value: float | int | None, *, currency: bool = False) -> str:
    """
    A number sized for a card, at any magnitude the data actually arrives at.

    Both ends matter. A group forecasting in trillions read "33160.31B" because
    the suffixes stopped at billions, and a conversion rate of 0.0000031 read
    "0" because everything under one was rounded to the nearest integer — the
    whole dashboard showed zeros for a perfectly ordinary series.
    """
    number = finite(value)
    if number is None:
        return "—"

    prefix = "$" if currency else ""
    sign = "-" if number < 0 else ""
    magnitude = abs(number)

    for threshold, suffix in SCALES:
        if magnitude >= threshold:
            digits = 1 if suffix == "K" else 2
            return f"{sign}{prefix}{_round(magnitude / threshold, digits)}{suffix}"

    if magnitude >= 1:
        return f"{sign}{prefix}{magnitude:,.0f}"
    if magnitude == 0:
        return f"{prefix}0"
    if magnitude < EXPONENT_BELOW:
        # Python pads the exponent to two digits and JavaScript does not, so
        # the pad comes off here rather than letting a card and a chart tick
        # spell the same number two ways.
        mantissa, exponent = f"{magnitude:.{SIGNIFICANT - 1}e}".split("e")
        return f"{sign}{prefix}{mantissa}e{int(exponent)}"

    # Enough decimals for three significant digits, then no trailing zeros:
    # "0.42" is the number, "0.420" is a claim about precision.
    places = SIGNIFICANT - 1 - math.floor(math.log10(magnitude))
    return f"{sign}{prefix}{_round(magnitude, places).rstrip('0').rstrip('.')}"
