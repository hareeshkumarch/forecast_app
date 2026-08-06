from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import ForecastError, NotFoundError, ValidationError
from app.core.logging import get_logger, request_id
from app.core.numbers import finite, storable
from app.core.security import (
    CredentialDecryptionError,
    decrypt_credentials,
    encrypt_credentials,
)
from app.core.storage import file_exists
from app.database.base import utcnow
from app.database.session import session_scope
from app.datasets import quality, queries
from app.datasets.profiler import is_currency_like
from app.forecasting.engine import (
    ForecastInput,
    ForecastOutput,
    InsufficientDataError,
    SegmentInput,
    SeriesInput,
    run_forecast,
)
from app.insights.engine import build_context, generate_insights
from app.insights.llm import LlmUsageRecord, llm_enabled, rewrite_insights
from app.models.entities import (
    CategoryForecast,
    Dataset,
    ExportJob,
    ForecastDriver,
    ForecastMetric,
    ForecastPoint,
    ForecastRun,
    ForecastSeries,
    Insight,
    LlmUsageEvent,
    ModelCandidate,
    RegionalForecast,
)
from app.models.enums import (
    ColumnRole,
    ForecastFrequency,
    GapFill,
    MeasureAggregation,
    ModelKind,
    OutlierTreatment,
    PointKind,
    RunStatus,
)
from app.services import dataset_service, insight_service
from app.services.job_runner import ProgressEvent, executors, publish_progress

logger = get_logger(__name__)


@dataclass(slots=True)
class RunOverrides:
    max_folds: int | None = None
    max_series: int | None = None
    metric_weights: dict[str, float] | None = None
    sarimax_order: list[int] | None = None
    gbm_max_depth: int | None = None
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_input_cost_per_million: float | None = None
    llm_output_cost_per_million: float | None = None

    SECRET_FIELDS = ("llm_api_key",)

    def is_empty(self) -> bool:
        return all(getattr(self, f.name) is None for f in fields(self))

    def to_stored(self) -> dict[str, object]:
        """Serialise for the run row, encrypting anything that is a secret."""
        stored: dict[str, object] = {}
        secrets: dict[str, str] = {}

        for field_def in fields(self):
            value = getattr(self, field_def.name)
            if value is None:
                continue
            if field_def.name in RunOverrides.SECRET_FIELDS:
                secrets[field_def.name] = str(value)
            else:
                stored[field_def.name] = value

        if secrets:
            ciphertext, _ = encrypt_credentials(secrets)
            stored["_secrets"] = ciphertext
        return stored

    @classmethod
    def from_stored(cls, stored: dict[str, object] | None) -> RunOverrides:
        if not stored:
            return cls()

        known = {field_def.name for field_def in fields(cls)}
        values = {key: value for key, value in stored.items() if key in known}

        ciphertext = stored.get("_secrets")
        if isinstance(ciphertext, str):
            try:
                values.update(decrypt_credentials(ciphertext))
            except CredentialDecryptionError:
                logger.warning("Could not decrypt the stored run options; continuing without them.")

        return cls(**values)  # type: ignore[arg-type]

    def llm_config(self) -> dict[str, object] | None:
        if not any(
            value is not None
            for value in (
                self.llm_api_key,
                self.llm_input_cost_per_million,
                self.llm_output_cost_per_million,
            )
        ):
            return None
        return {
            "llm_provider": self.llm_provider,
            "llm_api_key": self.llm_api_key,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "llm_input_cost_per_million": self.llm_input_cost_per_million,
            "llm_output_cost_per_million": self.llm_output_cost_per_million,
        }


#: The four groups the Reports screen offers, in its language rather than the
#: model's: "in progress" is one thing to a planner and two states here.
RUN_STATES: dict[str, tuple[RunStatus, ...]] = {
    "completed": (RunStatus.COMPLETED,),
    "active": (RunStatus.PENDING, RunStatus.RUNNING),
    "failed": (RunStatus.FAILED,),
}

RUN_SORTS: dict[str, Any] = {
    "newest": ForecastRun.created_at.desc(),
    "oldest": ForecastRun.created_at.asc(),
    "name": ForecastRun.name.asc(),
    "series": ForecastRun.series_count.desc(),
}
DEFAULT_RUN_SORT = "newest"
MAX_RUN_PAGE = 200


@dataclass(slots=True)
class RunPage:
    """A page of runs, how many there are, and how they divide by state."""

    rows: list[ForecastRun]
    total: int
    #: Every state's count under the same search, so the screen's counters stay
    #: true whichever one is being filtered on — and so they are counts of what
    #: exists rather than of what happened to be fetched.
    counts: dict[str, int]


def _run_search(term: str) -> Any:
    """Everything about a run someone might type: its name, what it forecasts, how."""
    like = f"%{term.strip().lower()}%"
    return or_(
        func.lower(ForecastRun.name).like(like),
        func.lower(ForecastRun.target_column).like(like),
        func.lower(func.coalesce(ForecastRun.selected_model, "")).like(like),
        func.lower(func.coalesce(ForecastRun.region_column, "")).like(like),
        func.lower(func.coalesce(ForecastRun.category_column, "")).like(like),
        func.lower(cast(ForecastRun.frequency, String)).like(like),
        func.lower(cast(ForecastRun.group_by, String)).like(like),
    )


async def list_runs(
    session: AsyncSession,
    *,
    search: str | None = None,
    state: str | None = None,
    sort: str = DEFAULT_RUN_SORT,
    limit: int = 50,
    offset: int = 0,
) -> RunPage:
    """
    A page of runs, filtered and ordered by the database rather than the browser.

    This used to return the newest fifty with no total and no way to ask for
    the fifty-first, which a screen listing forty-seven of them could not tell
    apart from "you have forty-seven". Searching happened in the browser over
    that truncated list, so a search for an older run reported that no such run
    existed.
    """
    narrowing = [_run_search(search)] if search and search.strip() else []

    grouped = await session.execute(
        select(ForecastRun.status, func.count()).where(*narrowing).group_by(ForecastRun.status)
    )
    by_status = {status: int(count) for status, count in grouped}
    counts = {
        "all": sum(by_status.values()),
        **{
            name: sum(by_status.get(status, 0) for status in states)
            for name, states in RUN_STATES.items()
        },
    }

    where = list(narrowing)
    if state in RUN_STATES:
        where.append(ForecastRun.status.in_(RUN_STATES[state]))

    total = counts["all"] if state not in RUN_STATES else counts[state]

    result = await session.execute(
        select(ForecastRun)
        .where(*where)
        .order_by(RUN_SORTS.get(sort, RUN_SORTS[DEFAULT_RUN_SORT]), ForecastRun.id.desc())
        .limit(max(1, min(limit, MAX_RUN_PAGE)))
        .offset(max(0, offset))
    )

    return RunPage(rows=list(result.scalars().all()), total=total, counts=counts)


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> ForecastRun:
    result = await session.execute(
        select(ForecastRun)
        .options(selectinload(ForecastRun.candidates), selectinload(ForecastRun.metrics))
        .where(ForecastRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise NotFoundError(f"No forecast run with id {run_id}.")
    return run


async def get_run_state(session: AsyncSession, run_id: uuid.UUID) -> ForecastRun:
    """Loads the run row without report relationships for status-only paths."""
    run = await session.get(ForecastRun, run_id)
    if run is None:
        raise NotFoundError(f"No forecast run with id {run_id}.")
    return run


async def latest_completed_run(session: AsyncSession) -> ForecastRun | None:
    result = await session.execute(
        select(ForecastRun)
        .where(ForecastRun.status == RunStatus.COMPLETED)
        .order_by(ForecastRun.completed_at.desc().nullslast(), ForecastRun.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def resolve_run(session: AsyncSession, run_id: uuid.UUID | None) -> ForecastRun | None:
    if run_id is not None:
        return await get_run(session, run_id)
    return await latest_completed_run(session)


async def create_run(
    session: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    name: str | None = None,
    time_column: str | None = None,
    target_column: str | None = None,
    weight_column: str | None = None,
    region_column: str | None = None,
    category_column: str | None = None,
    group_by: list[str] | None = None,
    frequency: ForecastFrequency | None = None,
    horizon: int | None = None,
    confidence_level: float = 0.8,
    aggregation: MeasureAggregation = MeasureAggregation.SUM,
    gap_fill: GapFill = GapFill.AUTO,
    outlier_treatment: OutlierTreatment = OutlierTreatment.NONE,
    max_folds: int | None = None,
    max_series: int | None = None,
    metric_weights: dict[str, float] | None = None,
    sarimax_order: list[int] | None = None,
    gbm_max_depth: int | None = None,
    llm_provider: str | None = None,
    llm_api_key: str | None = None,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_input_cost_per_million: float | None = None,
    llm_output_cost_per_million: float | None = None,
) -> ForecastRun:
    dataset = await dataset_service.get_dataset(session, dataset_id)

    if not await file_exists(dataset.parquet_path):
        raise ValidationError(
            "This dataset has no stored data file. Re-upload it before forecasting."
        )

    resolved_time = time_column or dataset.time_column
    resolved_target = target_column or dataset.target_column
    resolved_frequency = frequency or dataset.frequency or ForecastFrequency.MONTHLY
    resolved_horizon = horizon or dataset.horizon or 6

    if not resolved_time:
        raise ValidationError("No time column is configured. Select one before running a forecast.")
    if not resolved_target:
        raise ValidationError(
            "No target column is configured. Select one before running a forecast."
        )

    available = {column.name for column in dataset.columns}
    for label, value in (
        ("time", resolved_time),
        ("target", resolved_target),
        ("weight", weight_column),
        ("region", region_column),
        ("category", category_column),
    ):
        if value and value not in available:
            raise ValidationError(
                f"'{value}' is not a column in this dataset (selected as the {label} column).",
                detail={"available_columns": sorted(available)},
            )

    grain = _validated_grain(group_by, available, resolved_time, resolved_target)

    if region_column is None or category_column is None:
        guessed_region, guessed_category = dataset_service.guess_segment_columns(dataset)
        region_column = region_column or guessed_region
        category_column = category_column or guessed_category

    run = ForecastRun(
        dataset_id=dataset.id,
        name=name or f"{dataset.name} forecast",
        status=RunStatus.PENDING,
        progress=0.0,
        stage="queued",
        time_column=resolved_time,
        target_column=resolved_target,
        weight_column=weight_column,
        region_column=region_column,
        category_column=category_column,
        group_by=grain,
        frequency=resolved_frequency,
        horizon=resolved_horizon,
        confidence_level=confidence_level,
        aggregation=aggregation,
        gap_fill=gap_fill,
        outlier_treatment=outlier_treatment,
    )
    session.add(run)
    await session.flush()

    overrides = RunOverrides(
        max_folds=max_folds,
        max_series=max_series,
        metric_weights=metric_weights,
        sarimax_order=sarimax_order,
        gbm_max_depth=gbm_max_depth,
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_input_cost_per_million=llm_input_cost_per_million,
        llm_output_cost_per_million=llm_output_cost_per_million,
    )
    run.options = overrides.to_stored()
    await session.flush()

    publish_progress(
        ProgressEvent(
            run_id=run.id,
            status=RunStatus.PENDING,
            progress=0.0,
            stage="queued",
            message="Forecast queued.",
        )
    )
    return run


def _validated_grain(
    group_by: list[str] | None, available: set[str], time_column: str, target_column: str
) -> list[str]:
    """
    The columns a run forecasts at, checked before it is queued.

    Order matters — it is the order the tree nests in — so duplicates are
    rejected rather than quietly dropped. Grouping by the time or target column
    would ask for one series per period or per value, which is never meant.
    """
    if not group_by:
        return []

    grain = [column.strip() for column in group_by if column and column.strip()]

    unknown = [column for column in grain if column not in available]
    if unknown:
        raise ValidationError(
            f"{', '.join(repr(c) for c in unknown)} is not a column in this dataset "
            "(selected as a forecast grain).",
            detail={"available_columns": sorted(available)},
        )

    if len(set(grain)) != len(grain):
        raise ValidationError("The forecast grain lists the same column twice.")

    reserved = {column for column in grain if column in (time_column, target_column)}
    if reserved:
        raise ValidationError(
            f"{', '.join(repr(c) for c in sorted(reserved))} cannot be a forecast grain: "
            "it is already the time or target column."
        )

    return grain


_background_tasks: dict[uuid.UUID, asyncio.Task[RunStatus]] = {}


async def dispatch_run(session: AsyncSession, run: ForecastRun) -> None:
    """
    Hands the run to a Celery worker when a broker is configured, and otherwise
    fits it in this process. The single-node path keeps the platform runnable
    with nothing but Postgres.
    """
    if not settings.distributed:
        task = asyncio.create_task(execute_run(run.id))
        _background_tasks[run.id] = task

        def discard(done: asyncio.Task[RunStatus], run_id: uuid.UUID = run.id) -> None:
            if _background_tasks.get(run_id) is done:
                _background_tasks.pop(run_id, None)

        task.add_done_callback(discard)
        return

    from app.workers.tasks import run_forecast_task

    try:
        queued = await asyncio.to_thread(
            run_forecast_task.apply_async,
            args=[str(run.id), request_id.get()],
            task_id=str(run.id),
        )
    except Exception as exc:
        logger.exception("Could not queue forecast run %s", run.id)
        await mark_failed(run.id, exc)
        raise ForecastError(
            "The forecast could not be queued. The job broker is unreachable."
        ) from exc

    run.task_id = queued.id
    await session.flush()
    await session.commit()
    logger.info("Forecast run %s queued as task %s", run.id, queued.id)


async def cancel_run(session: AsyncSession, run_id: uuid.UUID) -> ForecastRun:
    run = await get_run_state(session, run_id)

    if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
        raise ValidationError(f"This run already finished with status '{run.status.value}'.")

    if settings.distributed and run.task_id:
        from app.workers.celery_app import celery_app

        task_ids = [run.task_id]
        if run.group_by:
            from app.services.series_service import cancellation_task_ids

            requested = RunOverrides.from_stored(run.options).max_series
            maximum = max(
                1,
                min(int(requested or queries.DEFAULT_MAX_SERIES), queries.DEFAULT_MAX_SERIES),
            )
            task_ids.extend(cancellation_task_ids(run_id, maximum))

        try:
            await asyncio.to_thread(
                celery_app.control.revoke,
                task_ids,
                terminate=True,
                signal="SIGTERM",
            )
        except Exception:
            # The atomic status guard still prevents a disconnected worker
            # from publishing or completing this run after cancellation.
            logger.warning("Could not deliver revoke for run %s", run_id, exc_info=True)
    elif task := _background_tasks.get(run_id):
        # Cancelling only the row allowed the in-process task to finish later
        # and overwrite `cancelled` with `completed`.
        task.cancel()

    run.status = RunStatus.FAILED
    run.stage = "cancelled"
    run.error_message = "Cancelled before it finished."
    run.completed_at = utcnow()
    await session.flush()

    publish_progress(
        ProgressEvent(
            run_id=run_id,
            status=RunStatus.FAILED,
            progress=run.progress,
            stage="cancelled",
            message="Forecast cancelled.",
            error="Cancelled before it finished.",
        )
    )
    return run


async def delete_run(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Permanently removes one settled run and its generated artifacts."""
    run = await get_run_state(session, run_id)
    if run.status not in (RunStatus.COMPLETED, RunStatus.FAILED):
        raise ValidationError("A forecast must finish or be cancelled before it can be cleared.")

    exported = await session.scalars(select(ExportJob.file_path).where(ExportJob.run_id == run_id))
    export_paths = [Path(path) for path in exported if path]
    task_id = run.task_id

    # Bulk deletion avoids materialising a large run's full series/point tree
    # just to remove it, and also works in SQLite where FK cascades may not be
    # enabled by the host process.
    await _clear_results(session, run_id)
    await session.execute(delete(ExportJob).where(ExportJob.run_id == run_id))
    await session.execute(delete(ForecastRun).where(ForecastRun.id == run_id))
    # Commit the database removal before touching Redis or files. If the
    # transaction fails, the run and every export remain intact rather than
    # leaving a stored report whose file was already removed.
    await session.commit()

    from app.services.progress_relay import forget_progress

    await forget_progress(run_id)

    if settings.distributed and task_id:
        from app.workers.celery_app import celery_app

        try:
            await asyncio.to_thread(celery_app.backend.forget, task_id)
        except Exception:
            logger.warning("Could not clear Celery result %s", task_id, exc_info=True)

    await asyncio.gather(*(_remove_export_file(path) for path in export_paths))


async def _remove_export_file(path: Path) -> None:
    """Deletes only generated files inside the configured export directory."""
    root = settings.exports_dir.resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        logger.warning("Refused to remove an export outside %s: %s", root, resolved)
        return
    try:
        await asyncio.to_thread(resolved.unlink, missing_ok=True)
    except OSError:
        logger.warning("Could not remove export %s", resolved, exc_info=True)


async def execute_run(run_id: uuid.UUID) -> RunStatus:
    """
    Fits the run and returns where it got to; never raises.

    A grouped run can come back RUNNING rather than COMPLETED: its top line is
    done and its series have been handed to the workers, which finish it.
    """
    try:
        return await _execute(run_id)
    except Exception as exc:
        logger.exception("Forecast run %s failed", run_id)
        await mark_failed(run_id, exc)
        return RunStatus.FAILED


async def _execute(run_id: uuid.UUID) -> RunStatus:
    if not await checkpoint_progress(run_id, 0.10, "aggregating", "Aggregating the series..."):
        return RunStatus.FAILED

    async with session_scope() as session:
        run = await get_run_state(session, run_id)
        if run.status is not RunStatus.RUNNING:
            return RunStatus.FAILED
        dataset = await dataset_service.get_dataset(session, run.dataset_id)
        grouped = bool(run.group_by)
        parquet_path = Path(dataset.parquet_path or "")
        driver_candidates = _driver_candidates(run, dataset)

    payload = await asyncio.to_thread(_build_payload, run, parquet_path, driver_candidates)

    if not await checkpoint_progress(
        run_id, 0.30, "backtesting", "Backtesting candidate models..."
    ):
        return RunStatus.FAILED

    try:
        if settings.distributed:
            output: ForecastOutput = await executors.run(
                _run_forecast_with_progress, payload, run_id, grouped
            )
        else:
            output = await executors.run(run_forecast, payload)
    except InsufficientDataError as exc:
        raise ForecastError(str(exc)) from exc

    # A grouped run is only part-way here: the top line is the number its
    # series still have to be fitted and reconciled to.
    if not await checkpoint_progress(
        run_id,
        0.58 if grouped else 0.90,
        "persisting",
        "Storing forecast results...",
    ):
        return RunStatus.FAILED

    async with session_scope() as session:
        run = await get_run_state(session, run_id)
        if run.status is not RunStatus.RUNNING:
            return RunStatus.FAILED
        await _persist_output(session, run, output)
        overrides = RunOverrides.from_stored(run.options)

    if not await checkpoint_progress(
        run_id,
        0.62 if grouped else 0.96,
        "generating_insights",
        "Generating insights...",
    ):
        return RunStatus.FAILED

    async with session_scope() as session:
        run = await get_run_state(session, run_id)
        if run.status is not RunStatus.RUNNING:
            return RunStatus.FAILED
        await _persist_insights(
            session,
            run,
            output,
            llm_config=overrides.llm_config(),
        )

    if grouped:
        from app.services import series_service

        return await series_service.forecast_series(run_id)

    completed = await complete_run(run_id)
    return RunStatus.COMPLETED if completed else RunStatus.FAILED


async def checkpoint_progress(run_id: uuid.UUID, progress: float, stage: str, message: str) -> bool:
    """Persists a coarse checkpoint so polling survives a Redis outage."""
    now = utcnow()
    values: dict[str, object] = {
        "status": RunStatus.RUNNING,
        "progress": progress,
        "stage": stage,
        "updated_at": now,
    }
    if stage == "aggregating":
        values["started_at"] = now

    async with session_scope() as session:
        result = await session.execute(
            update(ForecastRun)
            .where(
                ForecastRun.id == run_id,
                ForecastRun.status.in_((RunStatus.PENDING, RunStatus.RUNNING)),
            )
            .values(**values)
            .returning(ForecastRun.id)
        )
        accepted = result.first() is not None

    if accepted:
        _publish(run_id, RunStatus.RUNNING, progress, stage, message)
    return accepted


def _run_forecast_with_progress(
    payload: ForecastInput, run_id: uuid.UUID, grouped: bool
) -> ForecastOutput:
    """Runs inside Celery and publishes candidate-level progress to Redis."""

    def report(stage: str, done: int, total: int, message: str) -> None:
        if stage == "backtesting":
            start, end = (0.30, 0.52) if grouped else (0.30, 0.76)
            progress = start + (end - start) * (done / total if total else 1.0)
        elif stage == "fitting":
            start, end = (0.53, 0.56) if grouped else (0.78, 0.86)
            progress = start + (end - start) * (done / total if total else 1.0)
        else:
            start, end = (0.565, 0.575) if grouped else (0.87, 0.89)
            progress = start + (end - start) * (done / total if total else 1.0)
        _publish(run_id, RunStatus.RUNNING, progress, stage, message)

    return run_forecast(payload, report)


async def complete_run(run_id: uuid.UUID) -> bool:
    """Atomically marks an active run finished; cancellation always wins."""
    now = utcnow()
    async with session_scope() as session:
        result = await session.execute(
            update(ForecastRun)
            .where(
                ForecastRun.id == run_id,
                ForecastRun.status.in_((RunStatus.PENDING, RunStatus.RUNNING)),
            )
            .values(
                status=RunStatus.COMPLETED,
                progress=1.0,
                stage="complete",
                completed_at=now,
                updated_at=now,
            )
            .returning(ForecastRun.selected_model)
        )
        row = result.first()

    if row is None:
        return False
    selected = row[0].value if row[0] else None

    publish_progress(
        ProgressEvent(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            progress=1.0,
            stage="complete",
            message="Forecast complete.",
            selected_model=selected,
        )
    )
    return True


def _driver_candidates(run: ForecastRun, dataset: Dataset) -> list[str]:
    """
    The dataset's other numeric columns — the ones the profiler called measures
    and that this run is not already using for something else.

    The profiler has been labelling these since the first upload and nothing
    read them, so a price column, a promotion flag or a traffic count sitting
    beside the target was ignored however much it explained.
    """
    spoken_for = {
        run.time_column,
        run.target_column,
        run.weight_column,
        run.region_column,
        run.category_column,
        *(run.group_by or []),
    }

    return [
        column.name
        for column in dataset.columns
        if column.role is ColumnRole.MEASURE and column.name not in spoken_for
    ]


def _build_payload(
    run: ForecastRun, parquet_path: Path, driver_candidates: list[str] | None = None
) -> ForecastInput:
    series = queries.aggregate_series(
        parquet_path,
        run.time_column,
        run.target_column,
        run.frequency,
        weight_column=run.weight_column,
        aggregation=run.aggregation,
    )

    report = quality.build_report(
        rows_scanned=series.rows_scanned,
        rows_usable=series.rows_usable,
        duplicate_rows=series.duplicate_rows,
        row_counts=series.row_counts,
        periods=series.periods,
        values=series.values,
        frequency=run.frequency,
        fill=run.gap_fill,
    )

    periods, values, weights, fill_applied, _missing = quality.regularise(
        series.periods, series.values, series.weights, run.frequency, run.gap_fill
    )

    if run.outlier_treatment is OutlierTreatment.WINSORISE:
        values = quality.winsorise(values)

    regions = _segments(parquet_path, run, run.region_column)
    categories = _segments(parquet_path, run, run.category_column)

    overrides = RunOverrides.from_stored(run.options)

    drivers = queries.aggregate_candidate_drivers(
        parquet_path,
        run.time_column,
        driver_candidates or [],
        run.frequency,
        periods,
        aggregation=run.aggregation,
    )

    return ForecastInput(
        series=SeriesInput(periods=periods, values=values, weights=weights),
        drivers=drivers,
        target_label=run.target_column,
        quality={
            **report.as_dict(),
            "fill_applied": fill_applied.value,
            "aggregation": run.aggregation.value,
            "outlier_treatment": run.outlier_treatment.value,
        },
        frequency=run.frequency,
        horizon=run.horizon,
        confidence_level=run.confidence_level,
        regions=regions,
        categories=categories,
        max_folds=overrides.max_folds,
        metric_weights=overrides.metric_weights,
        model_options={
            "sarimax_order": overrides.sarimax_order,
            "gbm_max_depth": overrides.gbm_max_depth,
        },
    )


def _segments(parquet_path: Path, run: ForecastRun, column: str | None) -> list[SegmentInput]:
    if not column:
        return []

    # The window is derived from the history the aggregation actually finds —
    # a year wherever there are two of them — rather than fixed per frequency,
    # which made "versus the period before" mean a quarter on daily data and a
    # year on monthly.
    totals = queries.aggregate_segments(
        parquet_path,
        run.time_column,
        run.target_column,
        column,
        run.frequency,
    )
    return [
        SegmentInput(
            label=t.label,
            current_total=t.current_total,
            prior_total=t.prior_total,
            series=t.series,
            periods=t.periods,
            values=t.values,
        )
        for t in totals
    ]


async def _persist_output(session: AsyncSession, run: ForecastRun, output: ForecastOutput) -> None:
    await _clear_results(session, run.id)

    run.selected_model = ModelKind(output.selected_model)
    run.selection_rationale = output.selection_rationale
    run.leading_columns = [
        {"name": link.name, "lag": link.lag, "direction": link.direction}
        for link in output.leading_columns
    ]
    run.used_fallback = output.used_fallback
    run.fallback_reason = output.fallback_reason
    run.history_start = output.history_periods[0] if output.history_periods else None
    run.history_end = output.history_periods[-1] if output.history_periods else None
    run.forecast_start = output.forecast_periods[0] if output.forecast_periods else None
    run.forecast_end = output.forecast_periods[-1] if output.forecast_periods else None

    for candidate in output.candidates:
        session.add(
            ModelCandidate(
                run_id=run.id,
                model=ModelKind(candidate["model"]),
                rank=int(candidate["rank"]),
                selected=bool(candidate["selected"]),
                mae=finite(candidate["mae"]),
                rmse=finite(candidate["rmse"]),
                smape=finite(candidate["smape"]),
                wmape=finite(candidate["wmape"]),
                mase=finite(candidate.get("mase")),
                winkler=finite(candidate.get("winkler")),
                score=finite(candidate["score"]),
                folds=int(candidate["folds"]),
                fit_seconds=finite(candidate["fit_seconds"]),
                params=storable(candidate["params"]),
                failed=bool(candidate["failed"]),
                failure_reason=candidate["failure_reason"],
            )
        )

    previous = await _previous_metrics(session, run)
    for name, raw in output.metrics.items():
        # No row rather than a NaN one. The column cannot hold null, every
        # reader already asks for a metric by name and copes when it is not
        # there, and "we could not measure this" is exactly what absence says.
        value = finite(raw)
        if value is None:
            continue
        session.add(
            ForecastMetric(
                run_id=run.id,
                name=name,
                value=value,
                unit=_metric_unit(name),
                previous_value=finite(previous.get(name)),
            )
        )

    for index, period in enumerate(output.history_periods):
        fitted = output.fitted_values[index] if index < len(output.fitted_values) else None
        session.add(
            ForecastPoint(
                run_id=run.id,
                period=period,
                kind=PointKind.ACTUAL,
                actual=finite(output.history_values[index]),
                forecast=finite(fitted),
            )
        )

    for index, period in enumerate(output.forecast_periods):
        session.add(
            ForecastPoint(
                run_id=run.id,
                period=period,
                kind=PointKind.FORECAST,
                forecast=finite(output.point_forecast[index]),
                lower_bound=finite(output.lower_bound[index]),
                upper_bound=finite(output.upper_bound[index]),
                best_case=finite(output.best_case[index]),
                base_case=finite(output.base_case[index]),
                worst_case=finite(output.worst_case[index]),
            )
        )

    for segment in output.regions:
        session.add(
            RegionalForecast(
                run_id=run.id,
                region=segment.label,
                forecast_value=finite(segment.forecast_value) or 0.0,
                prior_year_value=finite(segment.prior_year_value),
                change_vs_last_year=finite(segment.change_vs_last_year),
                accuracy=finite(segment.accuracy),
                share=finite(segment.share) or 0.0,
                model=ModelKind(segment.model) if segment.model else None,
                accuracy_measured=segment.accuracy_measured,
            )
        )

    for rank, segment in enumerate(output.categories, start=1):
        session.add(
            CategoryForecast(
                run_id=run.id,
                category=segment.label,
                forecast_value=finite(segment.forecast_value) or 0.0,
                prior_year_value=finite(segment.prior_year_value),
                share=finite(segment.share) or 0.0,
                change_vs_last_year=finite(segment.change_vs_last_year),
                accuracy=segment.accuracy,
                rank=rank,
            )
        )

    for rank, driver in enumerate(output.drivers, start=1):
        session.add(
            ForecastDriver(
                run_id=run.id,
                driver=driver.name,
                impact_value=finite(driver.impact_value) or 0.0,
                impact_pct=finite(driver.impact_pct) or 0.0,
                change_vs_last_year=finite(driver.change_vs_last_year),
                direction=driver.direction,
                trend=driver.trend,
                rank=rank,
                method=driver.method,
            )
        )

    await session.flush()


async def _persist_insights(
    session: AsyncSession,
    run: ForecastRun,
    output: ForecastOutput,
    llm_config: dict[str, object] | None = None,
) -> None:
    previous_accuracy = (await _previous_metrics(session, run)).get("accuracy")

    context = build_context(
        output,
        frequency=run.frequency,
        confidence_level=run.confidence_level,
        previous_accuracy=previous_accuracy,
        currency_like=_looks_like_currency(run.target_column),
    )
    insights = generate_insights(context)

    # The computed wording, before the rewriter is allowed near it. Captured
    # here rather than after so a later rewrite always works from the
    # platform's own words, however many times it is asked for.
    computed = [(item.title, item.explanation, item.suggested_action) for item in insights]

    usage: list[LlmUsageRecord] = []
    if llm_enabled(llm_config):
        insights = rewrite_insights(insights, llm_config=llm_config, usage_sink=usage)

    applied = {record.insight_type for record in usage if record.applied}

    for rank, (insight, source) in enumerate(zip(insights, computed, strict=True), start=1):
        source_title, source_explanation, source_action = source
        session.add(
            Insight(
                run_id=run.id,
                type=insight.type,
                severity=insight.severity,
                title=insight.title,
                explanation=insight.explanation,
                suggested_action=insight.suggested_action,
                source_title=source_title,
                source_explanation=source_explanation,
                source_action=source_action,
                metric_name=insight.metric_name,
                metric_value=finite(insight.metric_value) or 0.0,
                metric_unit=insight.metric_unit,
                supporting_data=storable(insight.supporting_data),
                rank=rank,
                generated_at=insight.generated_at,
                llm_rewritten=insight.type.value in applied,
            )
        )

    insight_service.record_usage(session, run.id, usage)

    await session.flush()


async def _previous_metrics(session: AsyncSession, run: ForecastRun) -> dict[str, float]:
    result = await session.execute(
        select(ForecastRun)
        .where(
            ForecastRun.dataset_id == run.dataset_id,
            ForecastRun.id != run.id,
            ForecastRun.status == RunStatus.COMPLETED,
        )
        .order_by(ForecastRun.completed_at.desc().nullslast())
        .limit(1)
    )
    previous = result.scalar_one_or_none()
    if previous is None:
        return {}

    metrics = await session.execute(
        select(ForecastMetric).where(ForecastMetric.run_id == previous.id)
    )
    return {metric.name: metric.value for metric in metrics.scalars().all()}


async def _clear_results(session: AsyncSession, run_id: uuid.UUID) -> None:
    for model in (
        ModelCandidate,
        ForecastMetric,
        ForecastPoint,
        ForecastSeries,
        RegionalForecast,
        CategoryForecast,
        ForecastDriver,
        Insight,
        LlmUsageEvent,
    ):
        await session.execute(delete(model).where(model.run_id == run_id))


def _metric_unit(name: str) -> str:
    if name in ("smape", "wmape", "accuracy", "seasonal_strength"):
        return "percent"
    if name in ("backtest_folds", "seasonal_period"):
        return "count"
    # 1.0 is "no better than repeating last season", so it is a ratio and
    # showing it with a percent sign would say something quite different.
    if name == "mase":
        return "ratio"
    return "absolute"


def _looks_like_currency(column: str) -> bool:
    return is_currency_like(column)


def _publish(
    run_id: uuid.UUID, status: RunStatus, progress: float, stage: str, message: str
) -> None:
    publish_progress(
        ProgressEvent(run_id=run_id, status=status, progress=progress, stage=stage, message=message)
    )


async def mark_failed(run_id: uuid.UUID, exc: Exception) -> None:
    message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
    recorded = False

    try:
        async with session_scope() as session:
            now = utcnow()
            result = await session.execute(
                update(ForecastRun)
                .where(
                    ForecastRun.id == run_id,
                    ForecastRun.status.in_((RunStatus.PENDING, RunStatus.RUNNING)),
                )
                .values(
                    status=RunStatus.FAILED,
                    progress=1.0,
                    stage="failed",
                    error_message=message[:2000],
                    completed_at=now,
                    updated_at=now,
                )
                .returning(ForecastRun.id)
            )
            recorded = result.first() is not None
    except Exception:
        logger.exception("Could not record failure for run %s", run_id)

    # A cancelled, completed or explicitly cleared run is authoritative. Do
    # not resurrect a stale terminal frame after that transition won the race.
    if not recorded:
        return

    publish_progress(
        ProgressEvent(
            run_id=run_id,
            status=RunStatus.FAILED,
            progress=1.0,
            stage="failed",
            message="Forecast failed.",
            error=message,
        )
    )


async def points_for_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    start: date | None = None,
    end: date | None = None,
    series_id: uuid.UUID | None = None,
) -> list[ForecastPoint]:
    """
    The run's own top line by default. A grouped run also stores a curve per
    series, so pass series_id to scope to one of them; without it those rows
    would be summed into the headline.
    """
    statement = select(ForecastPoint).where(
        ForecastPoint.run_id == run_id,
        ForecastPoint.series_id == series_id
        if series_id is not None
        else ForecastPoint.series_id.is_(None),
    )
    if start is not None:
        statement = statement.where(ForecastPoint.period >= start)
    if end is not None:
        statement = statement.where(ForecastPoint.period <= end)

    result = await session.execute(statement.order_by(ForecastPoint.period, ForecastPoint.kind))
    return list(result.scalars().all())


async def dataset_for_run(session: AsyncSession, run: ForecastRun) -> Dataset:
    return await dataset_service.get_dataset(session, run.dataset_id)
