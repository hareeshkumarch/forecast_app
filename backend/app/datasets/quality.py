from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app.forecasting.frequency import add_periods
from app.models.enums import ForecastFrequency, GapFill, IssueSeverity

OUTLIER_SIGMAS = 3.5
LOW_COVERAGE = 0.90
SEVERE_COVERAGE = 0.60
PARTIAL_PERIOD_RATIO = 0.35
INTERMITTENT_ZERO_SHARE = 0.30
MIN_PERIODS = 2


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
    if requested is not GapFill.AUTO:
        return requested

    finite = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if finite.size == 0:
        return GapFill.ZERO

    zero_share = float(np.mean(np.isclose(finite, 0.0)))
    return GapFill.ZERO if zero_share >= INTERMITTENT_ZERO_SHARE else GapFill.INTERPOLATE


def regularise(
    periods: list[date],
    values: list[float],
    weights: list[float] | None,
    frequency: ForecastFrequency,
    fill: GapFill = GapFill.AUTO,
) -> tuple[list[date], list[float], list[float] | None, GapFill, list[int]]:
    if len(periods) < 2:
        return periods, values, weights, GapFill.NONE, []

    calendar = expected_periods(periods[0], periods[-1], frequency)
    observed = {period: index for index, period in enumerate(periods)}
    missing = [index for index, period in enumerate(calendar) if period not in observed]

    if not missing:
        return periods, values, weights, GapFill.NONE, []

    applied = resolve_fill(values, fill)
    if applied is GapFill.NONE:
        return periods, values, weights, GapFill.NONE, missing

    filled_values: list[float] = []
    filled_weights: list[float] | None = [] if weights is not None else None

    for period in calendar:
        source = observed.get(period)
        if source is None:
            filled_values.append(np.nan)
            if filled_weights is not None:
                filled_weights.append(0.0)
        else:
            filled_values.append(values[source])
            if filled_weights is not None and weights is not None:
                filled_weights.append(weights[source])

    array = np.asarray(filled_values, dtype=float)
    holes = ~np.isfinite(array)

    if applied is GapFill.ZERO:
        array[holes] = 0.0
    else:
        known = np.flatnonzero(~holes)
        array[holes] = np.interp(np.flatnonzero(holes), known, array[known])

    return calendar, [float(v) for v in array], filled_weights, applied, missing


def winsorise(values: list[float], sigmas: float = OUTLIER_SIGMAS) -> list[float]:
    array = np.asarray(values, dtype=float)
    if array.size < 5:
        return [float(v) for v in array]

    centre = float(np.median(array))
    deviation = float(np.median(np.abs(array - centre)))
    if deviation <= 0:
        return [float(v) for v in array]

    spread = 1.4826 * deviation * sigmas
    return [float(v) for v in np.clip(array, centre - spread, centre + spread)]


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
                IssueSeverity.SEVERE,
                "The target is the same value in every period.",
                "Choose a column that varies over time.",
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
