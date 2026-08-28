from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import polars as pl

from app.datasets.quality import expected_periods
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
) -> ValidationReport:
    assert_canonical(frame, covariates=covariates)

    required = min_history if min_history is not None else _required_history(frequency)
    report = ValidationReport(frequency=frequency, required_history=required)

    for (series_id,), group in frame.group_by([SERIES_ID], maintain_order=True):
        report.series.append(_check_series(str(series_id), group, frequency, required))

    report.series.sort(key=lambda item: item.series_id)
    return report


def _required_history(frequency: ForecastFrequency) -> int:
    return min_observations(frequency)


def _check_series(
    series_id: str,
    group: pl.DataFrame,
    frequency: ForecastFrequency,
    required: int,
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

    if values.size < required:
        findings.append(
            Finding(
                code="short_history",
                severity=IssueSeverity.WARNING,
                detail=f"{values.size} period(s) against the {required} a fitted model needs.",
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
    elif zero_share >= INTERMITTENT_ZERO_SHARE:
        findings.append(
            Finding(
                code="intermittent_demand",
                severity=IssueSeverity.WARNING,
                detail=f"{zero_share:.0%} of periods have no demand in them.",
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
    fallback = values.size < required or zero_share >= INTERMITTENT_ZERO_SHARE
    route = ROUTE_NONE if status == STATUS_REJECT else (ROUTE_FALLBACK if fallback else ROUTE_MODEL)

    return SeriesReport(
        series_id=series_id,
        status=status,
        route=route,
        observations=int(values.size),
        start=start,
        end=end,
        findings=findings,
    )


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
