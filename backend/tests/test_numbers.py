from __future__ import annotations

import pytest

from app.core.numbers import compact, finite, storable


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), None, "not a number", object()],
)
def test_a_value_that_is_not_a_number_becomes_absent(value: object) -> None:
    assert finite(value) is None


@pytest.mark.parametrize("value", [0.0, -1.5, 1e300, 42])
def test_a_real_number_passes_through(value: float) -> None:
    assert finite(value) == float(value)


def test_a_blob_bound_for_a_json_column_is_scrubbed_throughout() -> None:
    """
    A Holt-Winters fit on a flat series reports an AICc of -Infinity, quite
    correctly. Postgres rejects the whole insert over it, naming a token
    nobody wrote, and the run fails for a series the platform handled fine.
    """
    payload = {
        "aicc": float("-inf"),
        "order": [1, float("nan"), 2],
        "nested": {"score": float("inf"), "ok": 0.5},
        "converged": True,
        "label": "seasonal",
    }

    assert storable(payload) == {
        "aicc": None,
        "order": [1.0, None, 2.0],
        "nested": {"score": None, "ok": 0.5},
        "converged": True,
        "label": "seasonal",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # The top end: a group forecasting in trillions read "33160.31B".
        (33_160_310_000_000, "$33.16T"),
        (1.5e9, "$1.50B"),
        (2_500_000, "$2.50M"),
        (1250, "$1.3K"),
        (250, "$250"),
        (0, "$0"),
        # The bottom end: a conversion rate read "0", so did every card.
        # Half away from zero, matching what the browser does, so a card and
        # the report of the same run never disagree over a tie.
        (1_250_000_000_000, "$1.25T"),
        (0.42, "$0.42"),
        (0.0031, "$0.0031"),
        (3.1e-6, "$3.10e-6"),
        (-8.7e11, "-$870.00B"),
        (float("nan"), "—"),
        (None, "—"),
    ],
)
def test_a_number_is_readable_at_any_magnitude(value: object, expected: str) -> None:
    assert compact(value, currency=True) == expected  # type: ignore[arg-type]


def test_every_magnitude_from_the_very_small_to_the_very_large_is_legible() -> None:
    """No magnitude the data can arrive at may render as a bare zero or blank."""
    for exponent in range(-12, 16):
        rendered = compact(1.7 * 10.0**exponent)
        assert rendered not in ("", "0", "—"), f"1.7e{exponent} rendered as {rendered!r}"
        assert "nan" not in rendered.lower()


def test_the_currency_prefix_is_optional() -> None:
    assert compact(1500, currency=False) == "1.5K"
    assert compact(1500, currency=True) == "$1.5K"


SUFFIX_SCALE = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}


def _read_back(rendered: str) -> tuple[float, float]:
    """The number a reader would take from the text, and its last digit's worth."""
    scale = SUFFIX_SCALE.get(rendered[-1], 1.0)
    mantissa = rendered[:-1] if scale > 1.0 else rendered
    decimals = len(mantissa.partition(".")[2])
    return float(mantissa.replace(",", "")) * scale, 10.0**-decimals * scale


def test_a_reader_can_get_the_number_back_out_of_what_they_see() -> None:
    """
    Whatever a figure is rounded to, reading it back has to land within half of
    the last digit it shows — otherwise the display is not an abbreviation of
    the number, it is a different number.
    """
    for value in (1234.0, 4.2e12, 0.0031, 7.5e8, 250.0, 33_160_310_000_000.0):
        rendered = compact(value, currency=False)
        recovered, last_digit = _read_back(rendered)
        assert (
            abs(recovered - value) <= last_digit / 2 + 1e-9
        ), f"{value} rendered {rendered!r}, which reads back as {recovered}"
