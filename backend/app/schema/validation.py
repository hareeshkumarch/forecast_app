from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import polars as pl

from app.datasets.quality import expected_periods
from app.forecasting import routing
from app.forecasting.diagnostics import (
    SeriesProfile,
    detect_changepoints,
    minimum_history,
    profile_series,
)
from app.forecasting.frequency import min_observations
from app.forecasting.preparation import INTERMITTENT_ZERO_SHARE, OUTLIER_SIGMAS
from app.models.enums import ForecastFrequency, IssueSeverity
from app.schema.canonical import assert_canonical
from app.schema.contract import DS, SERIES_ID, Y

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_REJECT = "reject"

ROUTE_MODEL = "model"
ROUTE_FALLBACK = "fallback"
ROUTE_NONE = "none"

MIN_FITTABLE = 2
MAD_TO_SIGMA = 1.4826


@dataclass(slots=True, frozen=True)
class Finding:
    code: str
    severity: IssueSeverity
    detail: str
    count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "detail": self.detail,
            "count": self.count,
        }


@dataclass(slots=True)
class SeriesReport:
    series_id: str
    status: str
    route: str
    observations: int
    start: date | None
    end: date | None
    findings: list[Finding] = field(default_factory=list)
    #: What *this* series needed, which is not what the frequency needs in
    #: general — a weekly series with a yearly shape in it needs two of those
    #: years, and a flat one needs a fraction of that.
    required_history: int | None = None
    #: How the series was read: the same profile the engine routes models on.
    #: Carried here so the reader is told what the checks below were measured
    #: against rather than being handed a verdict with no basis.
    profile: dict[str, object] | None = None

    @property
    def codes(self) -> list[str]:
        return [finding.code for finding in self.findings]

    def as_dict(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "status": self.status,
            "route": self.route,
            "observations": self.observations,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "findings": [finding.as_dict() for finding in self.findings],
            "required_history": self.required_history,
            "profile": self.profile,
        }


@dataclass(slots=True)
class ValidationReport:
    frequency: ForecastFrequency
    required_history: int
    series: list[SeriesReport] = field(default_factory=list)

    @property
    def by_id(self) -> dict[str, SeriesReport]:
        return {report.series_id: report for report in self.series}

    @property
    def accepted(self) -> list[SeriesReport]:
        return [report for report in self.series if report.status != STATUS_REJECT]

    def counts(self) -> dict[str, int]:
        return {
            status: sum(1 for report in self.series if report.status == status)
            for status in (STATUS_OK, STATUS_WARN, STATUS_REJECT)
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "frequency": self.frequency.value,
            "required_history": self.required_history,
            "counts": self.counts(),
            "series": [report.as_dict() for report in self.series],
        }


def validate_canonical(
    frame: pl.DataFrame,
    *,
    frequency: ForecastFrequency,
    covariates: list[str] | None = None,
    min_history: int | None = None,
    adaptive: bool = True,
) -> ValidationReport:
    """Check every series against what that series actually needs.

    The floor on the report stays the frequency's, because it is what a reader
    comparing two datasets wants to see. What each series is *judged* against
    is its own: `adaptive` reads the same profile the engine routes models on
    and takes the history requirement, the intermittency verdict and the level
    shifts from it, rather than from constants that cannot know whether this
    particular series has a season in it.

    Pass `min_history` to pin the requirement for every series — an explicit
    number always wins — or `adaptive=False` for the fixed thresholds alone.
    """
    assert_canonical(frame, covariates=covariates)

    required = min_history if min_history is not None else _required_history(frequency)
    report = ValidationReport(frequency=frequency, required_history=required)

    for (series_id,), group in frame.group_by([SERIES_ID], maintain_order=True):
        report.series.append(
            _check_series(
                str(series_id),
                group,
                frequency,
                required,
                adaptive=adaptive and min_history is None,
            )
        )

    report.series.sort(key=lambda item: item.series_id)
    return report


def _required_history(frequency: ForecastFrequency) -> int:
    return min_observations(frequency)


def _check_series(
    series_id: str,
    group: pl.DataFrame,
    frequency: ForecastFrequency,
    required: int,
    *,
    adaptive: bool = False,
) -> SeriesReport:
    periods = group[DS].to_list()
    values = group[Y].to_numpy().astype(float)
    findings: list[Finding] = []

    start = periods[0] if periods else None
    end = periods[-1] if periods else None

    duplicates = len(periods) - len(set(periods))
    if duplicates:
        findings.append(
            Finding(
                code="duplicate_timestamps",
                severity=IssueSeverity.SEVERE,
                detail=f"{duplicates} period(s) appear more than once at this grain.",
                count=duplicates,
            )
        )

    if values.size < MIN_FITTABLE:
        findings.append(
            Finding(
                code="no_history",
                severity=IssueSeverity.SEVERE,
                detail=f"{values.size} observation(s); at least {MIN_FITTABLE} are needed to fit anything.",
                count=values.size,
            )
        )
        return SeriesReport(
            series_id=series_id,
            status=STATUS_REJECT,
            route=ROUTE_NONE,
            observations=int(values.size),
            start=start,
            end=end,
            findings=findings,
        )

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        findings.append(
            Finding(
                code="all_null",
                severity=IssueSeverity.SEVERE,
                detail="Every value in this series is empty.",
                count=int(values.size),
            )
        )
        return SeriesReport(
            series_id=series_id,
            status=STATUS_REJECT,
            route=ROUTE_NONE,
            observations=int(values.size),
            start=start,
            end=end,
            findings=findings,
        )

    profile = profile_series(finite, frequency) if adaptive else None
    #: What this series needs, not what the frequency needs on average. A
    #: weekly series carrying a yearly shape needs two of those years before
    #: anything can be fitted to it; a flat one needs a fraction of that, and
    #: warning about it is noise the reader has to learn to ignore.
    needed = max(MIN_FITTABLE, minimum_history(profile)) if profile else required

    if values.size < needed:
        because = (
            f" — seasonal at a period of {profile.seasonal_period}, so two cycles are the floor"
            if profile is not None and profile.has_seasonality
            else ""
        )
        findings.append(
            Finding(
                code="short_history",
                severity=IssueSeverity.WARNING,
                detail=f"{values.size} period(s) against the {needed} a fitted model needs{because}.",
                count=int(values.size),
            )
        )

    zero_share = float(np.mean(np.isclose(finite, 0.0)))
    if zero_share >= 1.0:
        findings.append(
            Finding(
                code="all_zero",
                severity=IssueSeverity.WARNING,
                detail="Every period in this series is zero.",
                count=int(finite.size),
            )
        )
    elif _is_intermittent(profile, zero_share):
        shape = (
            f" Demand arrives {profile.demand_class} at this grain."
            if profile is not None and profile.non_negative
            else ""
        )
        findings.append(
            Finding(
                code="intermittent_demand",
                severity=IssueSeverity.WARNING,
                detail=f"{zero_share:.0%} of periods have no demand in them.{shape}",
                count=int(np.sum(np.isclose(finite, 0.0))),
            )
        )
    elif float(np.ptp(finite)) == 0.0:
        findings.append(
            Finding(
                code="constant_target",
                severity=IssueSeverity.WARNING,
                detail="The target never changes across this series.",
                count=int(finite.size),
            )
        )

    negatives = int(np.sum(finite < 0))
    if negatives:
        findings.append(
            Finding(
                code="negative_values",
                severity=IssueSeverity.INFO,
                detail=f"{negatives} period(s) are below zero.",
                count=negatives,
            )
        )

    if start is not None and end is not None:
        gaps = len(expected_periods(start, end, frequency)) - len(set(periods))
        if gaps > 0:
            findings.append(
                Finding(
                    code="calendar_gaps",
                    severity=IssueSeverity.WARNING,
                    detail=f"{gaps} period(s) between the first and last row have no data.",
                    count=gaps,
                )
            )

    leading, trailing = _edge_nulls(values)
    if leading:
        findings.append(
            Finding(
                code="leading_nulls",
                severity=IssueSeverity.INFO,
                detail=f"The series opens with {leading} empty period(s).",
                count=leading,
            )
        )
    if trailing:
        findings.append(
            Finding(
                code="trailing_nulls",
                severity=IssueSeverity.WARNING,
                detail=f"The series ends with {trailing} empty period(s).",
                count=trailing,
            )
        )

    if profile is not None:
        # A step onto a new plateau is the one finding that changes what the
        # rest of the history is worth: everything before the break describes
        # a business that no longer exists, and a model fitted across it will
        # average the two.
        step = _level_shift(finite)
        if step is not None:
            findings.append(
                Finding(
                    code="level_shift",
                    severity=IssueSeverity.WARNING,
                    detail=(
                        f"The level steps onto a new plateau around period {step + 1} of "
                        f"{finite.size}; history either side of it describes different behaviour."
                    ),
                    count=int(step + 1),
                )
            )

    outliers = _outlier_count(finite)
    if outliers:
        findings.append(
            Finding(
                code="outliers",
                severity=IssueSeverity.INFO,
                detail=f"{outliers} period(s) sit more than {OUTLIER_SIGMAS} robust deviations from the median.",
                count=outliers,
            )
        )

    status = (
        STATUS_REJECT
        if any(f.severity is IssueSeverity.SEVERE for f in findings)
        else (STATUS_WARN if findings else STATUS_OK)
    )
    fallback = values.size < needed or _is_intermittent(profile, zero_share)
    route = ROUTE_NONE if status == STATUS_REJECT else (ROUTE_FALLBACK if fallback else ROUTE_MODEL)

    return SeriesReport(
        series_id=series_id,
        status=status,
        route=route,
        observations=int(values.size),
        start=start,
        end=end,
        findings=findings,
        required_history=int(needed),
        profile=profile.as_dict() if profile is not None else None,
    )


#: How far apart the two plateaus have to be, in units of the scatter inside
#: them, before the split is worth telling anybody about.
LEVEL_SHIFT_SIGMAS = 3.0

#: And how much bigger than either side's own drift. This is the whole test.
#: A rising series splits under any mean-difference scan — the second half of
#: anything trending has a higher mean than the first — so the question is not
#: "do the halves differ" but "are they each flat and yet different". Without
#: it every trending series in the dataset carries a level-shift warning, and
#: a warning that fires on healthy data is one the reader learns to skip.
LEVEL_SHIFT_OVER_DRIFT = 2.0

#: Below this there is not enough either side to say anything about the shape
#: of either side.
MIN_LEVEL_SHIFT_HISTORY = 12


def _level_shift(values: np.ndarray) -> int | None:
    """The index a genuine step sits at, or None when the change is a slope.

    Deliberately stricter than `detect_changepoints`, which the engine uses to
    decide how far back to fit from. Being wrong there costs a slightly short
    training window; being wrong here puts a warning in front of a person, and
    those have to be worth reading.
    """
    if values.size < MIN_LEVEL_SHIFT_HISTORY:
        return None

    candidates = detect_changepoints(values)
    if not candidates:
        return None

    index = candidates[0]
    before, after = values[: index + 1], values[index + 1 :]
    if before.size < 3 or after.size < 3:
        return None

    step = abs(float(np.mean(after) - np.mean(before)))
    scatter = max(float(np.std(before)), float(np.std(after)))
    if scatter <= 0.0:
        return index if step > 0 else None
    if step < LEVEL_SHIFT_SIGMAS * scatter:
        return None

    # How far each half travels under its own straight line. A plateau barely
    # moves; half of a trend moves about as much as the step does.
    drift = max(_span(before), _span(after))
    if step < LEVEL_SHIFT_OVER_DRIFT * drift:
        return None

    return index


def _span(values: np.ndarray) -> float:
    """How far a straight line through these points rises across them."""
    if values.size < 2:
        return 0.0
    x = np.arange(values.size, dtype=float)
    slope = float(np.polyfit(x, values, 1)[0])
    return abs(slope) * (values.size - 1)


def _is_intermittent(profile: SeriesProfile | None, zero_share: float) -> bool:
    """Whether this series is bursty, judged the way the router judges it.

    The fixed share is kept as the answer when there is no profile, and as a
    floor when there is: the demand class is the better instrument, but it is
    built from the interval between sales and a series can clear that bar
    while still being mostly empty.
    """
    if zero_share >= INTERMITTENT_ZERO_SHARE:
        return True
    if profile is None or not profile.non_negative:
        return False
    return profile.demand_class in {routing.INTERMITTENT, routing.LUMPY, routing.NO_DEMAND}


def _edge_nulls(values: np.ndarray) -> tuple[int, int]:
    holes = ~np.isfinite(values)
    known = np.flatnonzero(~holes)
    if known.size == 0:
        return int(values.size), 0
    return int(known[0]), int(values.size - 1 - known[-1])


def _outlier_count(finite: np.ndarray) -> int:
    if finite.size < 5:
        return 0
    centre = float(np.median(finite))
    deviation = float(np.median(np.abs(finite - centre)))
    if deviation <= 0:
        return 0
    spread = MAD_TO_SIGMA * deviation * OUTLIER_SIGMAS
    return int(np.sum(np.abs(finite - centre) > spread))
