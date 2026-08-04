from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date
from pathlib import Path

import polars as pl
from sqlalchemy import select
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
    RegionalForecast,
)
from app.models.enums import ExportFormat, ExportStatus
from app.services import forecast_service

logger = get_logger(__name__)

MEDIA_TYPES: dict[ExportFormat, str] = {
    ExportFormat.CSV: "text/csv",
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ExportFormat.JSON: "application/json",
}


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


async def _collect_rows(session: AsyncSession, run: ForecastRun) -> list[dict]:
    result = await session.execute(
        select(ForecastPoint)
        .where(ForecastPoint.run_id == run.id)
        .order_by(ForecastPoint.period, ForecastPoint.kind)
    )

    return [
        {
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
        for point in result.scalars().all()
    ]


async def _summary_sheets(session: AsyncSession, run: ForecastRun) -> dict[str, list[dict]]:
    metrics = await session.execute(select(ForecastMetric).where(ForecastMetric.run_id == run.id))
    regions = await session.execute(
        select(RegionalForecast).where(RegionalForecast.run_id == run.id)
    )
    categories = await session.execute(
        select(CategoryForecast).where(CategoryForecast.run_id == run.id).order_by(CategoryForecast.rank)
    )
    drivers = await session.execute(
        select(ForecastDriver).where(ForecastDriver.run_id == run.id).order_by(ForecastDriver.rank)
    )

    return {
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
    frame = pl.DataFrame(rows, infer_schema_length=None)

    if export_format is ExportFormat.CSV:


        frame.write_csv(path)
        return

    if export_format is ExportFormat.JSON:
        payload = {
            "run": {
                "id": str(run.id),
                "name": run.name,
                "selected_model": run.selected_model.value if run.selected_model else None,
                "selection_rationale": run.selection_rationale,
                "frequency": run.frequency.value,
                "horizon": run.horizon,
                "confidence_level": run.confidence_level,
                "used_fallback": run.used_fallback,
                "fallback_reason": run.fallback_reason,
                "history_start": run.history_start.isoformat() if run.history_start else None,
                "history_end": run.history_end.isoformat() if run.history_end else None,
                "forecast_start": run.forecast_start.isoformat() if run.forecast_start else None,
                "forecast_end": run.forecast_end.isoformat() if run.forecast_end else None,
                "exported_at": utcnow().isoformat(),
            },
            "points": rows,
            **sheets,
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return


    try:
        import xlsxwriter

        workbook = xlsxwriter.Workbook(str(path), {"default_date_format": "yyyy-mm-dd"})
        try:
            frame.write_excel(workbook=workbook, worksheet="forecast", autofit=True)
            for sheet_name, sheet_rows in sheets.items():
                if not sheet_rows:
                    continue
                pl.DataFrame(sheet_rows, infer_schema_length=None).write_excel(
                    workbook=workbook, worksheet=sheet_name[:31], autofit=True
                )
        finally:
            workbook.close()
    except (ImportError, ModuleNotFoundError, Exception) as exc:
        logger.warning("xlsxwriter unavailable (%s); falling back to CSV file generation.", exc)
        frame.write_csv(path)


def export_media_type(export_format: ExportFormat) -> str:
    return MEDIA_TYPES[export_format]


def export_filename(run: ForecastRun, export_format: ExportFormat) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in run.name).strip("-")
    return f"{safe or 'forecast'}-{run.id.hex[:8]}.{export_format.value}"
