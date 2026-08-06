from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, overload


@overload
def finite(value: None) -> None: ...


@overload
def finite(value: float | int) -> float | None: ...


def finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def storable(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: storable(value) for key, value in payload.items()}
    if isinstance(payload, list | tuple):
        return [storable(item) for item in payload]
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, float | int):
        return finite(payload)
    return payload


SCALES: tuple[tuple[float, str], ...] = (
    (1e12, "T"),
    (1e9, "B"),
    (1e6, "M"),
    (1e3, "K"),
)

EXPONENT_BELOW = 1e-4

SIGNIFICANT = 3


def _round(value: float, places: int) -> str:
    try:
        quantum = Decimal(1).scaleb(-places)
        return str(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return f"{value:.{places}f}"


def compact(value: float | int | None, *, currency: bool = False, symbol: str = "$") -> str:
    number = finite(value)
    if number is None:
        return "—"

    prefix = symbol if currency else ""
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
        mantissa, exponent = f"{magnitude:.{SIGNIFICANT - 1}e}".split("e")
        return f"{sign}{prefix}{mantissa}e{int(exponent)}"

    places = SIGNIFICANT - 1 - math.floor(math.log10(magnitude))
    return f"{sign}{prefix}{_round(magnitude, places).rstrip('0').rstrip('.')}"
