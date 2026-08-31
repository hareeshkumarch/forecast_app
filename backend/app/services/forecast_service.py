from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, fields
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import budget, cache, metrics
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
from app.datasets.profiler import is_currency_like, natural_aggregation
from app.forecasting.engine import (
    ForecastInput,
    ForecastOutput,
    InsufficientDataError,
    SegmentInput,
    SeriesInput,
    run_forecast,
)
from app.forecasting.preparation import Preparation
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
    ColumnKind,
    ColumnRole,
    ForecastFrequency,
    GapFill,
    IssueSeverity,
    MeasureAggregation,
    ModelKind,
    OutlierTreatment,
    PointKind,
    RunStatus,
)
from app.services import dataset_service, insight_service
from app.services.job_runner import ProgressEvent, as_utc, executors, publish_progress

logger = get_logger(__name__)


@dataclass(slots=True)
class RunOverrides:
    max_folds: int | None = None
    max_series: int | None = None
    metric_weights: dict[str, float] | None = None
    sarimax_order: list[int] | None = None
    gbm_max_depth: int | None = None
    gbm_learning_rate: float | None = None
    candidate_models: list[str] | None = None
    prophet_changepoint_prior_scale: float | None = None
    prophet_interval_width: float | None = None
    outlier_mad_threshold: float | None = None
    complexity_penalty_scale: float | None = None
    driver_columns: list[str] | None = None
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
MAX_RUN_PAGE = settings.api_max_page_size

# Deliberately looser than quality.OUTLIER_SIGMAS: clipping a series a run was
# asked to forecast should only catch the spikes nothing can explain.
WINSORISE_SIGMAS = 6.0

#: How much a simulated interval widens per unit of intervention. A scenario
#: that moves the total by half again is a long way outside anything the
#: backtest measured, and a band that stayed the same relative width would be
#: claiming an accuracy nobody has for a world that does not exist yet.
SIMULATION_BAND_WIDENING = 0.5


@dataclass(slots=True)
class RunPage:
    rows: list[ForecastRun]
    total: int
    counts: dict[str, int]


def _run_search(term: str) -> Any:
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
        .limit(max(1, min(limit, settings.api_max_page_size)))
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


async def run_for_idempotency_key(
    session: AsyncSession, idempotency_key: str | None
) -> ForecastRun | None:
    if not idempotency_key:
        return None
    result = await session.execute(
        select(ForecastRun).where(ForecastRun.idempotency_key == idempotency_key).limit(1)
    )
    return result.scalar_one_or_none()


async def create_run(
    session: AsyncSession,
    *,
    created_by_user_id: uuid.UUID | None = None,
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
    aggregation: MeasureAggregation | None = None,
    gap_fill: GapFill = GapFill.AUTO,
    outlier_treatment: OutlierTreatment = OutlierTreatment.NONE,
    max_folds: int | None = None,
    max_series: int | None = None,
    metric_weights: dict[str, float] | None = None,
    sarimax_order: list[int] | None = None,
    gbm_max_depth: int | None = None,
    gbm_learning_rate: float | None = None,
    candidate_models: list[str] | None = None,
    prophet_changepoint_prior_scale: float | None = None,
    prophet_interval_width: float | None = None,
    outlier_mad_threshold: float | None = None,
    complexity_penalty_scale: float | None = None,
    driver_columns: list[str] | None = None,
    llm_provider: str | None = None,
    llm_api_key: str | None = None,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_input_cost_per_million: float | None = None,
    llm_output_cost_per_million: float | None = None,
    idempotency_key: str | None = None,
    retry_of_run_id: uuid.UUID | None = None,
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

    kinds = {column.name: column.kind for column in dataset.columns}
    _require_kind(kinds, resolved_time, ColumnKind.DATE, "time")
    _require_kind(kinds, resolved_target, ColumnKind.NUMERIC, "target")
    _require_kind(kinds, weight_column, ColumnKind.NUMERIC, "weight")

    grain = _validated_grain(group_by, available, resolved_time, resolved_target)
    resolved_aggregation = _validated_aggregation(aggregation, resolved_target)
    _validated_drivers(driver_columns, kinds)
    _validated_models(candidate_models)
    resolved_horizon = _validated_horizon(
        resolved_horizon, dataset, resolved_frequency, requested=horizon is not None
    )

    if region_column is None or category_column is None:
        guessed_region, guessed_category = dataset_service.guess_segment_columns(dataset)
        region_column = region_column or guessed_region
        category_column = category_column or guessed_category

    decision = await _admission_for(dataset, grain)
    if not decision.accepted:
        raise ValidationError(decision.message, detail=decision.as_dict())

    run = ForecastRun(
        dataset_id=dataset.id,
        created_by_user_id=created_by_user_id,
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
        aggregation=resolved_aggregation,
        gap_fill=gap_fill,
        outlier_treatment=outlier_treatment,
        idempotency_key=idempotency_key,
        retry_of_run_id=retry_of_run_id,
    )
    session.add(run)
    await session.flush()

    overrides = RunOverrides(
        max_folds=max_folds,
        max_series=max_series,
        metric_weights=metric_weights,
        sarimax_order=sarimax_order,
        gbm_max_depth=gbm_max_depth,
        gbm_learning_rate=gbm_learning_rate,
        candidate_models=candidate_models,
        prophet_changepoint_prior_scale=prophet_changepoint_prior_scale,
        prophet_interval_width=prophet_interval_width,
        outlier_mad_threshold=outlier_mad_threshold,
        complexity_penalty_scale=complexity_penalty_scale,
        driver_columns=driver_columns,
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_input_cost_per_million=llm_input_cost_per_million,
        llm_output_cost_per_million=llm_output_cost_per_million,
    )
    run.options = {**overrides.to_stored(), "admission": decision.as_dict()}
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


async def retry_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
) -> ForecastRun:
    original = await get_run_state(session, run_id)
    if original.status != RunStatus.FAILED:
        raise ValidationError("Only failed forecast runs can be retried.")

    existing = await run_for_idempotency_key(session, idempotency_key)
    if existing is not None:
        return existing

    overrides = RunOverrides.from_stored(original.options)
    return await create_run(
        session,
        dataset_id=original.dataset_id,
        name=f"{original.name} retry"[:200],
        time_column=original.time_column,
        target_column=original.target_column,
        weight_column=original.weight_column,
        region_column=original.region_column,
        category_column=original.category_column,
        group_by=list(original.group_by or []),
        frequency=original.frequency,
        horizon=original.horizon,
        confidence_level=original.confidence_level,
        aggregation=original.aggregation,
        gap_fill=original.gap_fill,
        outlier_treatment=original.outlier_treatment,
        max_folds=overrides.max_folds,
        max_series=overrides.max_series,
        metric_weights=overrides.metric_weights,
        sarimax_order=overrides.sarimax_order,
        gbm_max_depth=overrides.gbm_max_depth,
        gbm_learning_rate=overrides.gbm_learning_rate,
        candidate_models=overrides.candidate_models,
        prophet_changepoint_prior_scale=overrides.prophet_changepoint_prior_scale,
        prophet_interval_width=overrides.prophet_interval_width,
        outlier_mad_threshold=overrides.outlier_mad_threshold,
        complexity_penalty_scale=overrides.complexity_penalty_scale,
        driver_columns=overrides.driver_columns,
        llm_provider=overrides.llm_provider,
        llm_api_key=overrides.llm_api_key,
        llm_model=overrides.llm_model,
        llm_base_url=overrides.llm_base_url,
        llm_input_cost_per_million=overrides.llm_input_cost_per_million,
        llm_output_cost_per_million=overrides.llm_output_cost_per_million,
        idempotency_key=idempotency_key,
        retry_of_run_id=original.id,
    )


#: What each role needs the column to actually hold, in the words a customer
#: would use for it.
KIND_DESCRIPTION: dict[ColumnKind, str] = {
    ColumnKind.DATE: "dates",
    ColumnKind.NUMERIC: "numbers",
    ColumnKind.CATEGORICAL: "categories",
    ColumnKind.BOOLEAN: "true/false values",
    ColumnKind.TEXT: "text",
}


def _require_kind(
    kinds: dict[str, ColumnKind], column: str | None, expected: ColumnKind, role: str
) -> None:
    """Refuse a column that cannot play the part it was given.

    Checking only that the name exists lets a text column be chosen as the
    target: DuckDB's TRY_CAST turns every row of it into NULL, the series comes
    back empty, and the run fails somewhere far from the choice that caused it.
    """
    if not column:
        return

    actual = kinds.get(column)
    if actual is None or actual is expected:
        return

    raise ValidationError(
        f"'{column}' holds {KIND_DESCRIPTION.get(actual, actual.value)}, and the {role} "
        f"column has to hold {KIND_DESCRIPTION[expected]}.",
        detail={
            "column": column,
            "role": role,
            "found_kind": actual.value,
            "required_kind": expected.value,
            "candidates": sorted(name for name, kind in kinds.items() if kind is expected),
        },
    )


def _validated_aggregation(requested: MeasureAggregation | None, target: str) -> MeasureAggregation:
    """How the target adds up over the rows inside a period.

    Nothing checked this. Summing is right for a quantity and meaningless for
    a level: add up a unit price or a conversion rate over the rows in a month
    and the figure grows with how many rows there were, so the series being
    forecast is order volume wearing the target's name.

    An explicit choice is honoured — somebody who asks to sum a column called
    price may have a reason, and a run that answers a different question from
    the one it was asked is worse than one that answers awkwardly. Left unset,
    the column's own name decides.
    """
    return requested if requested is not None else natural_aggregation(target)


def _validated_drivers(driver_columns: list[str] | None, kinds: dict[str, ColumnKind]) -> None:
    """A driver that was asked for and cannot be used has to say so.

    The selection used to be filtered down to the numeric columns still going
    spare, and anything left over was dropped without a word — so a run
    configured to read three drivers could read none of them and still report
    success.
    """
    if not driver_columns:
        return

    unknown = [name for name in driver_columns if name not in kinds]
    if unknown:
        raise ValidationError(
            f"{', '.join(repr(name) for name in unknown)} is not a column in this dataset "
            "(selected as a driver).",
            detail={"available_columns": sorted(kinds)},
        )

    not_numeric = [name for name in driver_columns if kinds[name] is not ColumnKind.NUMERIC]
    if not_numeric:
        raise ValidationError(
            f"{', '.join(repr(name) for name in not_numeric)} cannot be a driver: a driver "
            "has to hold numbers.",
            detail={
                "numeric_columns": sorted(
                    name for name, kind in kinds.items() if kind is ColumnKind.NUMERIC
                )
            },
        )


def _validated_models(candidate_models: list[str] | None) -> None:
    """Refuse a model roster that names something the engine does not have.

    A name that matched nothing used to leave the filter empty, and an empty
    filter fell back to the full roster — so restricting a run to one model
    could quietly run all of them.
    """
    if not candidate_models:
        return

    known = {kind.value for kind in ModelKind}
    unknown = [name for name in candidate_models if str(name).lower() not in known]
    if unknown:
        raise ValidationError(
            f"{', '.join(repr(name) for name in unknown)} is not a model this engine can fit.",
            detail={"available_models": sorted(known)},
        )


#: A forecast may reach this far past the history it was fitted on. Beyond it
#: the horizon is longer than the evidence, and no backtest fold can be built
#: that measures it.
MAX_HORIZON_SHARE = 0.5


def _validated_horizon(
    horizon: int, dataset: Dataset, frequency: ForecastFrequency, *, requested: bool
) -> int:
    """Hold the horizon to what the history can speak to.

    Asking for twenty-four months from twelve months of history is not a hard
    forecast, it is an unmeasurable one: no backtest fold can hold out a window
    that long, so the accuracy shown beside it was never tested at that range.

    A horizon somebody chose is refused rather than quietly shortened — a run
    that answers a different question from the one it was asked is worse than
    one that does not answer. A horizon nobody chose is the default, and that
    is clamped, because failing a run over a number the user never typed is
    just as unhelpful.
    """
    if horizon <= 0:
        raise ValidationError("The forecast horizon has to be at least one period.")

    start, end = dataset.date_range_start, dataset.date_range_end
    if start is None or end is None:
        return horizon

    periods = len(quality.expected_periods(start, end, frequency))
    ceiling = int(periods * MAX_HORIZON_SHARE)
    if ceiling < 1 or horizon <= ceiling:
        return horizon

    if not requested:
        return max(1, ceiling)

    raise ValidationError(
        f"A {horizon}-period horizon is longer than this dataset can support: it holds "
        f"{periods} {frequency.value} periods, so at most {ceiling} can be forecast "
        "and measured.",
        detail={"periods_available": periods, "max_horizon": ceiling},
    )


async def _admission_for(dataset: Dataset, grain: list[str]) -> budget.AdmissionDecision:
    if not grain:
        return budget.admission(1)
    return budget.admission(
        await asyncio.to_thread(
            queries.distinct_series_count, Path(dataset.parquet_path or ""), grain
        )
    )


def _validated_grain(
    group_by: list[str] | None, available: set[str], time_column: str, target_column: str
) -> list[str]:
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


async def recover_interrupted_runs() -> int:
    """Turn orphaned single-process jobs into explicit, retryable failures.

    An in-process executor has no durable queue across a service restart. A run
    left as pending/running would otherwise look alive forever. Distributed
    Celery jobs are durable and are deliberately left alone.
    """
    if settings.distributed:
        return 0
    async with session_scope() as session:
        result = await session.execute(
            update(ForecastRun)
            .where(ForecastRun.status.in_((RunStatus.PENDING, RunStatus.RUNNING)))
            .values(
                status=RunStatus.FAILED,
                stage="interrupted",
                progress=0.0,
                error_message=(
                    "The service restarted before this run finished. Retry it to use the "
                    "same configuration."
                ),
                completed_at=utcnow(),
            )
        )
        return int(result.rowcount or 0)


async def dispatch_run(session: AsyncSession, run: ForecastRun) -> None:
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
            logger.warning("Could not deliver revoke for run %s", run_id, exc_info=True)
    elif task := _background_tasks.get(run_id):
        task.cancel()

    run.status = RunStatus.FAILED
    run.stage = "cancelled"
    run.error_message = "Cancelled before it finished."
    run.completed_at = utcnow()
    await session.flush()

    # Counted apart from a failure even though the row records both the same
    # way. An operator watching the failure rate needs to know which half of
    # it is the platform breaking and which half is somebody changing their
    # mind — a graph that cannot tell them apart is a graph nobody trusts.
    _record_terminal(
        RunStatus.FAILED,
        started_at=run.started_at,
        finished_at=run.completed_at,
        label="cancelled",
    )

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


def _record_terminal(
    status: RunStatus,
    *,
    started_at: datetime | None,
    finished_at: datetime | None,
    label: str | None = None,
) -> None:
    """Count a run that has finished, and how long it took.

    Duration comes from the row's own timestamps rather than a stopwatch in
    this process, which is the only version that works when the run executed
    on a Celery worker and this is the process that noticed. A run with no
    `started_at` never began, so it is counted but not timed — a zero in the
    histogram would drag every percentile down and make an outage look fast.

    Both ends go through `as_utc` first. SQLite hands back a naive datetime
    from the same column Postgres returns aware, and subtracting one from the
    other raises — inside the completion path, which would turn a finished
    forecast into a failed one over a measurement nobody asked for.
    Instrumentation must never be able to break the thing it instruments.
    """
    metrics.forecast_runs.inc(status=label or status.value)
    if started_at is None or finished_at is None:
        return
    elapsed = (as_utc(finished_at) - as_utc(started_at)).total_seconds()
    if elapsed >= 0:
        metrics.forecast_run_seconds.observe(elapsed)


async def delete_run(session: AsyncSession, run_id: uuid.UUID) -> None:
    run = await get_run_state(session, run_id)
    if run.status not in (RunStatus.COMPLETED, RunStatus.FAILED):
        raise ValidationError("A forecast must finish or be cancelled before it can be cleared.")

    exported = await session.scalars(select(ExportJob.file_path).where(ExportJob.run_id == run_id))
    export_paths = [Path(path) for path in exported if path]
    task_id = run.task_id

    await _clear_results(session, run_id)
    await session.execute(delete(ExportJob).where(ExportJob.run_id == run_id))
    await session.execute(delete(ForecastRun).where(ForecastRun.id == run_id))
    await session.commit()

    from app.services.progress_relay import forget_progress

    await forget_progress(run_id)
    # The dashboard entries derived from this run can never be served again —
    # their keys carry a revision that no longer exists — but there is no
    # reason to hold the memory until they expire.
    cache.forget_run(run_id)

    if settings.distributed and task_id:
        from app.workers.celery_app import celery_app

        try:
            await asyncio.to_thread(celery_app.backend.forget, task_id)
        except Exception:
            logger.warning("Could not clear Celery result %s", task_id, exc_info=True)

    await asyncio.gather(*(_remove_export_file(path) for path in export_paths))


async def _remove_export_file(path: Path) -> None:
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
        # The reporting variant used to be reserved for the distributed
        # deployment, on the assumption that only a Celery worker had a way to
        # report back. A pool worker has one too, so the single-node path used
        # the silent variant and sat at 30% for the whole model search — the
        # slowest and least predictable part of a run, and the one stretch a
        # watching user most needs to see moving.
        output: ForecastOutput = await executors.run(
            _run_forecast_with_progress, payload, run_id, grouped
        )
    except InsufficientDataError as exc:
        raise ForecastError(str(exc)) from exc

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
            .returning(ForecastRun.selected_model, ForecastRun.started_at)
        )
        row = result.first()

    if row is None:
        return False
    selected = row[0].value if row[0] else None
    _record_terminal(RunStatus.COMPLETED, started_at=row[1], finished_at=now)

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
    overrides = RunOverrides.from_stored(run.options)
    spoken_for = {
        run.time_column,
        run.target_column,
        run.weight_column,
        run.region_column,
        run.category_column,
        *(run.group_by or []),
    }

    measures = [
        column.name
        for column in dataset.columns
        if (column.role is ColumnRole.MEASURE or column.kind.value in ("numeric", "float", "int"))
        and column.name not in spoken_for
    ]

    if overrides.driver_columns:
        allowed = set(overrides.driver_columns)
        return [col for col in measures if col in allowed]
    return measures


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

    # A severe issue is the profiler saying this series cannot be forecast —
    # no usable rows, too few periods, a target that never changes. Running
    # anyway produces a number, and a number produced from that is worse than
    # no answer, because it is indistinguishable from a real one.
    if report.blocked:
        severe = [issue for issue in report.issues if issue.severity is IssueSeverity.SEVERE]
        raise ForecastError(
            "This series cannot be forecast as configured. "
            + " ".join(f"{issue.message} {issue.remedy}" for issue in severe),
            detail={"issues": [issue.as_dict() for issue in severe]},
        )

    # The calendar is made regular here; the holes in it are left as holes.
    # Filling them, and clipping the outliers, are modelling decisions the
    # engine makes fold by fold — done once over the whole history they would
    # put the validation windows into their own training data.
    aligned = quality.align_calendar(
        series.periods, series.values, series.weights, run.frequency, run.gap_fill
    )
    periods, values, weights = aligned.periods, aligned.values, aligned.weights

    overrides = RunOverrides.from_stored(run.options)

    preparation = Preparation(
        fill=run.gap_fill if aligned.missing and aligned.regular else GapFill.NONE,
        # The override is a count of robust deviations, which is what `sigmas` is.
        winsorise_sigmas=(
            (overrides.outlier_mad_threshold or WINSORISE_SIGMAS)
            if run.outlier_treatment is OutlierTreatment.WINSORISE
            else None
        ),
    )
    fill_applied = (
        quality.resolve_fill(values, run.gap_fill)
        if preparation.fill is not GapFill.NONE
        else GapFill.NONE
    )

    regions = _segments(parquet_path, run, run.region_column)
    categories = _segments(parquet_path, run, run.category_column)

    drivers = queries.aggregate_candidate_drivers(
        parquet_path,
        run.time_column,
        driver_candidates or [],
        run.frequency,
        periods,
        aggregation=run.aggregation,
        # A driver adds up the way its own name says it does. Taking the
        # target's aggregation says something about the target and nothing
        # about the driver, and summing a price or a conversion rate over the
        # rows in a month produces a number that tracks the row count.
        per_column={name: natural_aggregation(name) for name in driver_candidates or []},
    )

    return ForecastInput(
        series=SeriesInput(periods=periods, values=values, weights=weights),
        preparation=preparation,
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
            "gbm_learning_rate": overrides.gbm_learning_rate,
            "candidate_models": overrides.candidate_models,
            "prophet_changepoint_prior_scale": overrides.prophet_changepoint_prior_scale,
            "prophet_interval_width": overrides.prophet_interval_width,
            "complexity_penalty_scale": overrides.complexity_penalty_scale,
            "outlier_mad_threshold": overrides.outlier_mad_threshold,
        },
    )


def _segments(parquet_path: Path, run: ForecastRun, column: str | None) -> list[SegmentInput]:
    if not column:
        return []

    totals = queries.aggregate_segments(
        parquet_path,
        run.time_column,
        run.target_column,
        column,
        run.frequency,
        # The same reducer the headline number uses. Summing a breakdown of a
        # measure the run averages gives regions that do not add up to the
        # total they are shown beside.
        aggregation=run.aggregation,
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
    run.options = {**(run.options or {}), **storable(output.diagnostics)}

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
                .returning(ForecastRun.id, ForecastRun.started_at)
            )
            row = result.first()
            recorded = row is not None
            if row is not None:
                _record_terminal(RunStatus.FAILED, started_at=row[1], finished_at=now)
    except Exception:
        logger.exception("Could not record failure for run %s", run_id)

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


async def driver_leverage(session: AsyncSession, run_id: uuid.UUID) -> dict[str, float]:
    """Each driver's share of the movement this run explained, as a 0..1 fraction.

    A driver holding 40% of the impact moves the total by 40% of whatever is asked
    of it, so a 1.5x on that driver lifts the forecast by 20%, not 50%.
    """
    result = await session.execute(
        select(ForecastDriver.driver, ForecastDriver.impact_pct).where(
            ForecastDriver.run_id == run_id
        )
    )
    return {name: max(0.0, min(float(pct or 0.0) / 100.0, 1.0)) for name, pct in result.all()}


def _driver_scale(multipliers: dict[str, float], leverage: dict[str, float]) -> float:
    """Combine per-driver multipliers into one factor, weighted by their leverage."""
    scale = 1.0
    for name, multiplier in multipliers.items():
        scale *= 1.0 + leverage.get(name, 0.0) * (multiplier - 1.0)
    return max(scale, 0.0)


async def simulate_what_if(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    volume_multiplier: float = 1.0,
    target_shift_pct: float = 0.0,
    driver_multipliers: dict[str, float] | None = None,
) -> dict[str, Any]:
    run = await get_run(session, run_id)
    if run.status is not RunStatus.COMPLETED:
        raise ValidationError("Only completed forecast runs can be simulated.")

    points = await points_for_run(session, run.id)
    forecast_points = [p for p in points if p.kind is PointKind.FORECAST]

    if not forecast_points:
        raise ValidationError("This forecast run has no forecast points to simulate.")

    driver_mults = dict(driver_multipliers or {})
    leverage = await driver_leverage(session, run.id)

    unknown = sorted(set(driver_mults) - set(leverage))
    if unknown:
        known = ", ".join(sorted(leverage)) or "none"
        raise ValidationError(
            f"This run has no driver named {', '.join(unknown)}. Available drivers: {known}."
        )

    effective_shift = 1.0 + (target_shift_pct / 100.0)
    effective_scale = volume_multiplier * effective_shift * _driver_scale(driver_mults, leverage)

    simulated_points = []
    baseline_total = 0.0
    simulated_total = 0.0
    simulated_best_total = 0.0
    simulated_worst_total = 0.0

    # An assumption the model was never fitted under is less certain than the
    # forecast it came from, and scaling the band by the same factor as the
    # point claims otherwise: it reports the measured relative uncertainty for
    # a scenario nothing measured. The band widens with the size of the
    # intervention, around the re-priced point rather than around zero.
    intervention = abs(effective_scale - 1.0)
    widening = 1.0 + SIMULATION_BAND_WIDENING * intervention

    def scaled(value: float | None, base: float, simulated: float) -> float | None:
        if value is None:
            return None
        offset = (float(value) - base) * effective_scale
        return simulated + offset * widening

    for point in sorted(forecast_points, key=lambda p: p.period):
        base = float(point.forecast or 0.0)
        sim = base * effective_scale
        low = scaled(point.lower_bound, base, sim)
        high = scaled(point.upper_bound, base, sim)
        best = scaled(point.best_case, base, sim)
        worst = scaled(point.worst_case, base, sim)
        best = best if best is not None else (high if high is not None else sim)
        worst = worst if worst is not None else (low if low is not None else sim)

        delta = sim - base
        delta_pct = (delta / abs(base) * 100.0) if base != 0 else 0.0

        baseline_total += base
        simulated_total += sim
        simulated_best_total += best
        simulated_worst_total += worst

        simulated_points.append(
            {
                "period": point.period,
                "baseline_forecast": round(base, 4),
                "simulated_forecast": round(sim, 4),
                "simulated_lower_bound": round(low, 4) if low is not None else None,
                "simulated_upper_bound": round(high, 4) if high is not None else None,
                "simulated_best_case": round(best, 4) if best is not None else None,
                "simulated_worst_case": round(worst, 4) if worst is not None else None,
                "delta": round(delta, 4),
                "delta_pct": round(delta_pct, 2),
            }
        )

    total_delta = simulated_total - baseline_total
    total_delta_pct = (total_delta / abs(baseline_total) * 100.0) if baseline_total != 0 else 0.0

    return {
        "run_id": run.id,
        "volume_multiplier": volume_multiplier,
        "target_shift_pct": target_shift_pct,
        "driver_multipliers": driver_mults,
        "baseline_total": round(baseline_total, 4),
        "simulated_total": round(simulated_total, 4),
        "total_delta": round(total_delta, 4),
        "total_delta_pct": round(total_delta_pct, 2),
        "simulated_best_case_total": round(simulated_best_total, 4),
        "simulated_worst_case_total": round(simulated_worst_total, 4),
        "method": "repriced_from_measured_leverage",
        "intervention_size": round(intervention, 4),
        "points": simulated_points,
    }
