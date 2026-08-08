from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app.forecasting.frequency import add_periods
from app.forecasting.preparation import INTERMITTENT_ZERO_SHARE, OUTLIER_SIGMAS
from app.forecasting.preparation import fill_gaps as _fill_gaps
from app.forecasting.preparation import resolve_fill as _resolve_fill
from app.forecasting.preparation import winsorise as _winsorise
from app.models.enums import ForecastFrequency, GapFill, IssueSeverity

LOW_COVERAGE = 0.90
SEVERE_COVERAGE = 0.60
PARTIAL_PERIOD_RATIO = 0.35
MIN_PERIODS = 2

__all__ = [
    "INTERMITTENT_ZERO_SHARE",
    "LOW_COVERAGE",
    "MIN_PERIODS",
    "OUTLIER_SIGMAS",
    "PARTIAL_PERIOD_RATIO",
    "SEVERE_COVERAGE",
    "AlignedSeries",
    "QualityIssue",
    "QualityReport",
    "align_calendar",
    "build_report",
    "expected_periods",
    "regularise",
    "resolve_fill",
    "winsorise",
]


@dataclass(slots=True)
class QualityIssue:
    code: str
    severity: IssueSeverity
    message: str
    remedy: str
    count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "remedy": self.remedy,
            "count": self.count,
        }


@dataclass(slots=True)
class QualityReport:
    rows_scanned: int
    rows_usable: int
    periods_present: int
    periods_expected: int
    gap_count: int
    longest_gap: int
    duplicate_rows: int
    partial_periods: int
    outlier_periods: int
    negative_periods: int
    zero_periods: int
    constant_target: bool
    range_start: date | None
    range_end: date | None
    fill_applied: GapFill
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        if self.periods_expected <= 0:
            return 0.0
        return self.periods_present / self.periods_expected

    @property
    def blocked(self) -> bool:
        return any(issue.severity is IssueSeverity.SEVERE for issue in self.issues)

    def as_dict(self) -> dict[str, object]:
        return {
            "rows_scanned": self.rows_scanned,
            "rows_usable": self.rows_usable,
            "periods_present": self.periods_present,
            "periods_expected": self.periods_expected,
            "coverage": round(self.coverage, 4),
            "gap_count": self.gap_count,
            "longest_gap": self.longest_gap,
            "duplicate_rows": self.duplicate_rows,
            "partial_periods": self.partial_periods,
            "outlier_periods": self.outlier_periods,
            "negative_periods": self.negative_periods,
            "zero_periods": self.zero_periods,
            "constant_target": self.constant_target,
            "fill_applied": self.fill_applied.value,
            "blocked": self.blocked,
            "issues": [issue.as_dict() for issue in self.issues],
        }


def expected_periods(start: date, end: date, frequency: ForecastFrequency) -> list[date]:
    periods: list[date] = []
    cursor = start
    guard = 0

    while cursor <= end and guard < 100_000:
        periods.append(cursor)
        cursor = add_periods(cursor, 1, frequency)
        guard += 1

    return periods


def resolve_fill(values: list[float], requested: GapFill) -> GapFill:
    return _resolve_fill(np.asarray(values, dtype=float), requested)


@dataclass(slots=True)
class AlignedSeries:
    """A series on its regular calendar, with the holes still holes.

    `values` carries NaN wherever the calendar expects a period the data does
    not have. Filling them is a modelling decision that belongs to whoever is
    about to fit — done here it would be done once, over the whole history,
    and every backtest fold would train on numbers derived from its own
    validation window.
    """

    periods: list[date]
    values: list[float]
    weights: list[float] | None
    missing: list[int]
    #: False when the series was left on its own irregular index, because no
    #: filling was asked for and a fabricated calendar would be worse.
    regular: bool = True


def align_calendar(
    periods: list[date],
    values: list[float],
    weights: list[float] | None,
    frequency: ForecastFrequency,
    fill: GapFill = GapFill.AUTO,
) -> AlignedSeries:
    """Put a series on its regular calendar without filling the gaps."""
    if len(periods) < 2:
        return AlignedSeries(periods, values, weights, [], regular=False)

    calendar = expected_periods(periods[0], periods[-1], frequency)
    observed = {period: index for index, period in enumerate(periods)}
    missing = [index for index, period in enumerate(calendar) if period not in observed]

    if not missing:
        return AlignedSeries(periods, values, weights, [])
    if fill is GapFill.NONE:
        # Nothing will fill them, so a calendar full of holes is worse than the
        # irregular index the data actually has.
        return AlignedSeries(periods, values, weights, missing, regular=False)

    holed: list[float] = []
    holed_weights: list[float] | None = [] if weights is not None else None

    for period in calendar:
        source = observed.get(period)
        if source is None:
            holed.append(float("nan"))
            if holed_weights is not None:
                holed_weights.append(0.0)
        else:
            holed.append(values[source])
            if holed_weights is not None and weights is not None:
                holed_weights.append(weights[source])

    return AlignedSeries(calendar, holed, holed_weights, missing)


def regularise(
    periods: list[date],
    values: list[float],
    weights: list[float] | None,
    frequency: ForecastFrequency,
    fill: GapFill = GapFill.AUTO,
) -> tuple[list[date], list[float], list[float] | None, GapFill, list[int]]:
    """Align and fill in one step, for callers that want the whole series at once."""
    aligned = align_calendar(periods, values, weights, frequency, fill)
    if not aligned.missing or not aligned.regular:
        return aligned.periods, aligned.values, aligned.weights, GapFill.NONE, aligned.missing

    array = np.asarray(aligned.values, dtype=float)
    applied = _resolve_fill(array, fill)
    filled = _fill_gaps(array, applied)

    return (
        aligned.periods,
        [float(v) for v in filled],
        aligned.weights,
        applied,
        aligned.missing,
    )


def winsorise(values: list[float], sigmas: float = OUTLIER_SIGMAS) -> list[float]:
    return [float(v) for v in _winsorise(np.asarray(values, dtype=float), sigmas)]


def _outlier_count(values: np.ndarray) -> int:
    if values.size < 5:
        return 0

    differenced = np.diff(values)
    centre = float(np.median(differenced))
    deviation = float(np.median(np.abs(differenced - centre)))
    scale = 1.4826 * deviation
    if scale <= 0:
        scale = float(np.mean(np.abs(differenced - centre)))
    if scale <= 0:
        return 0

    scaled = np.abs(differenced - centre) / scale
    return int(np.sum(scaled > OUTLIER_SIGMAS))


def build_report(
    *,
    rows_scanned: int,
    rows_usable: int,
    duplicate_rows: int,
    row_counts: list[int],
    periods: list[date],
    values: list[float],
    frequency: ForecastFrequency,
    fill: GapFill,
) -> QualityReport:
    issues: list[QualityIssue] = []
    array = np.asarray(values, dtype=float)

    calendar = expected_periods(periods[0], periods[-1], frequency) if periods else []
    observed = set(periods)
    missing = [period for period in calendar if period not in observed]

    longest = 0
    current = 0
    for period in calendar:
        if period in observed:
            current = 0
        else:
            current += 1
            longest = max(longest, current)

    typical_rows = float(np.median(row_counts)) if row_counts else 0.0
    partial = (
        int(np.sum(np.asarray(row_counts, dtype=float) < typical_rows * PARTIAL_PERIOD_RATIO))
        if typical_rows > 0
        else 0
    )

    outliers = _outlier_count(array)
    negatives = int(np.sum(array < 0)) if array.size else 0
    zeros = int(np.sum(np.isclose(array, 0.0))) if array.size else 0
    constant = bool(array.size >= 2 and np.allclose(array, array[0]))

    applied = resolve_fill(values, fill) if missing else GapFill.NONE

    report = QualityReport(
        rows_scanned=rows_scanned,
        rows_usable=rows_usable,
        periods_present=len(periods),
        periods_expected=len(calendar),
        gap_count=len(missing),
        longest_gap=longest,
        duplicate_rows=duplicate_rows,
        partial_periods=partial,
        outlier_periods=outliers,
        negative_periods=negatives,
        zero_periods=zeros,
        constant_target=constant,
        range_start=periods[0] if periods else None,
        range_end=periods[-1] if periods else None,
        fill_applied=applied,
        issues=issues,
    )

    if rows_usable == 0:
        issues.append(
            QualityIssue(
                "no_usable_rows",
                IssueSeverity.SEVERE,
                "No rows survived parsing the time and target columns.",
                "Check that the selected columns hold dates and numbers.",
            )
        )
    elif len(periods) < MIN_PERIODS:
        issues.append(
            QualityIssue(
                "too_few_periods",
                IssueSeverity.SEVERE,
                f"Only {len(periods)} period(s) after aggregating to {frequency.value}.",
                "Pick a finer frequency, or upload a longer history.",
                len(periods),
            )
        )

    if constant:
        issues.append(
            QualityIssue(
                "constant_target",
                # A warning rather than a refusal. A discontinued line, or one
                # that has not launched, is the same value in every period —
                # usually zero — and the flat forecast is the right answer for
                # it. What cannot be done is *measuring* that forecast: every
                # percentage error divides by the series total.
                IssueSeverity.WARNING,
                "The target is the same value in every period.",
                "The forecast will be that same value, and its accuracy cannot be "
                "measured against a series that never moves.",
            )
        )

    coverage = report.coverage
    if missing:
        severity = IssueSeverity.WARNING if coverage >= SEVERE_COVERAGE else IssueSeverity.SEVERE
        issues.append(
            QualityIssue(
                "calendar_gaps",
                severity,
                f"{len(missing)} of {len(calendar)} periods have no data "
                f"({coverage:.0%} coverage, longest run {longest}).",
                f"Gaps are filled by {applied.value} so the calendar stays regular; "
                "supply the missing periods for a cleaner fit.",
                len(missing),
            )
        )
    elif coverage < LOW_COVERAGE:
        issues.append(
            QualityIssue(
                "low_coverage",
                IssueSeverity.WARNING,
                f"Only {coverage:.0%} of the calendar is covered.",
                "Fill in the missing history where you can.",
            )
        )

    if duplicate_rows:
        issues.append(
            QualityIssue(
                "duplicate_timestamps",
                IssueSeverity.INFO,
                f"{duplicate_rows} rows share a period with another row.",
                "Expected for transactional data; if these are accidental duplicates "
                "from a join, deduplicate before uploading.",
                duplicate_rows,
            )
        )

    if partial:
        issues.append(
            QualityIssue(
                "partial_periods",
                IssueSeverity.WARNING,
                f"{partial} period(s) hold far fewer rows than the rest.",
                "Usually a part-reported first or last period — trim the range so it "
                "is not read as a real dip.",
                partial,
            )
        )

    if outliers:
        issues.append(
            QualityIssue(
                "outliers",
                IssueSeverity.INFO,
                f"{outliers} period-to-period jump(s) exceed {OUTLIER_SIGMAS} robust deviations.",
                "Leave them if they are real events; enable outlier treatment to damp them.",
                outliers,
            )
        )

    if negatives:
        issues.append(
            QualityIssue(
                "negative_values",
                IssueSeverity.INFO,
                f"{negatives} period(s) aggregate to a negative value.",
                "Fine for margin or net-of-returns measures; unexpected for volumes.",
                negatives,
            )
        )

    return report
