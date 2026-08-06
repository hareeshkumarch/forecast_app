from __future__ import annotations

import asyncio
import uuid
from datetime import date
from pathlib import Path

import polars as pl
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.database.base import utcnow
from app.models.entities import (
    CategoryForecast,
    ExportJob,
    ForecastDriver,
    ForecastMetric,
    ForecastPoint,
    ForecastRun,
    ForecastSeries,
    RegionalForecast,
)
from app.models.enums import ExportFormat, ExportStatus
from app.services import forecast_service

logger = get_logger(__name__)

MEDIA_TYPES: dict[ExportFormat, str] = {
    ExportFormat.CSV: "text/csv",
    ExportFormat.PDF: "application/pdf",
}

PDF_MAX_ROWS = 120


async def create_export(
    session: AsyncSession, run_id: uuid.UUID, export_format: ExportFormat
) -> ExportJob:
    run = await forecast_service.get_run(session, run_id)

    job = ExportJob(run_id=run.id, format=export_format, status=ExportStatus.PENDING)
    session.add(job)
    await session.flush()

    try:
        rows = await _collect_rows(session, run)
        if not rows:
            raise ValidationError("This run has no forecast points to export.")

        sheets = await _summary_sheets(session, run)
        path = settings.exports_dir / f"{run.id}-{job.id}.{export_format.value}"

        await asyncio.to_thread(settings.ensure_directories)
        await asyncio.to_thread(_write, rows, path, export_format, run, sheets)

        job.status = ExportStatus.READY
        job.file_path = str(path)
        job.file_size_bytes = (await asyncio.to_thread(path.stat)).st_size
        job.row_count = len(rows)
        job.completed_at = utcnow()
    except Exception as exc:
        logger.exception("Export failed for run %s", run_id)
        job.status = ExportStatus.FAILED
        job.error_message = (getattr(exc, "message", None) or str(exc))[:1000]
        await session.flush()
        raise

    await session.flush()
    return job


TOP_LINE = "Total"


async def _collect_rows(session: AsyncSession, run: ForecastRun) -> list[dict]:
    result = await session.execute(
        select(ForecastPoint, ForecastSeries.label)
        .outerjoin(ForecastSeries, ForecastPoint.series_id == ForecastSeries.id)
        .where(ForecastPoint.run_id == run.id)
        .order_by(ForecastSeries.label.nulls_first(), ForecastPoint.period, ForecastPoint.kind)
    )

    return [
        {
            "series": label or TOP_LINE,
            "period": point.period.isoformat() if isinstance(point.period, date) else point.period,
            "kind": point.kind.value,
            "actual": point.actual,
            "forecast": point.forecast,
            "lower_bound": point.lower_bound,
            "upper_bound": point.upper_bound,
            "best_case": point.best_case,
            "base_case": point.base_case,
            "worst_case": point.worst_case,
        }
        for point, label in result.all()
    ]


async def _summary_sheets(session: AsyncSession, run: ForecastRun) -> dict[str, list[dict]]:
    metrics = await session.execute(select(ForecastMetric).where(ForecastMetric.run_id == run.id))
    regions = await session.execute(
        select(RegionalForecast).where(RegionalForecast.run_id == run.id)
    )
    categories = await session.execute(
        select(CategoryForecast)
        .where(CategoryForecast.run_id == run.id)
        .order_by(CategoryForecast.rank)
    )
    drivers = await session.execute(
        select(ForecastDriver).where(ForecastDriver.run_id == run.id).order_by(ForecastDriver.rank)
    )

    series = await session.execute(
        select(ForecastSeries)
        .where(ForecastSeries.run_id == run.id, ForecastSeries.level > 0)
        .order_by(
            ForecastSeries.wmape.is_(None).asc(),
            (func.abs(ForecastSeries.forecast_total) * ForecastSeries.wmape).desc(),
        )
    )

    return {
        "series": [
            {
                "series": s.label,
                "forecast": s.forecast_total,
                "wmape_pct": s.wmape,
                "value_at_risk": (
                    abs(s.forecast_total) * s.wmape / 100.0 if s.wmape is not None else None
                ),
                "measured": s.accuracy_measured,
            }
            for s in series.scalars().all()
        ],
        "metrics": [
            {"name": m.name, "value": m.value, "unit": m.unit, "previous_value": m.previous_value}
            for m in metrics.scalars().all()
        ],
        "regions": [
            {
                "region": r.region,
                "forecast": r.forecast_value,
                "change_vs_last_year_pct": r.change_vs_last_year,
                "accuracy_pct": r.accuracy,
                "share_pct": r.share,
            }
            for r in regions.scalars().all()
        ],
        "categories": [
            {
                "category": c.category,
                "forecast": c.forecast_value,
                "share_pct": c.share,
                "change_vs_last_year_pct": c.change_vs_last_year,
            }
            for c in categories.scalars().all()
        ],
        "drivers": [
            {
                "driver": d.driver,
                "impact": d.impact_value,
                "impact_pct": d.impact_pct,
                "direction": d.direction,
                "method": d.method,
            }
            for d in drivers.scalars().all()
        ],
    }


def _write(
    rows: list[dict],
    path: Path,
    export_format: ExportFormat,
    run: ForecastRun,
    sheets: dict[str, list[dict]],
) -> None:
    if export_format is ExportFormat.CSV:
        pl.DataFrame(rows, infer_schema_length=None).write_csv(path)
        return

    from app.reporting import pdf

    pdf.build(path, run, rows, sheets, max_rows=PDF_MAX_ROWS)


def export_media_type(export_format: ExportFormat) -> str:
    return MEDIA_TYPES[export_format]


def export_filename(run: ForecastRun, export_format: ExportFormat) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in run.name).strip("-")
    return f"{safe or 'forecast'}-{run.id.hex[:8]}.{export_format.value}"
