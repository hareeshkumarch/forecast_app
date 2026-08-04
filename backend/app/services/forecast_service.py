from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ForecastError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.base import utcnow
from app.database.session import session_scope
from app.datasets import queries
from app.forecasting.engine import (
    ForecastInput,
    ForecastOutput,
    InsufficientDataError,
    SegmentInput,
    SeriesInput,
    run_forecast,
)
from app.insights.engine import build_context, generate_insights
from app.insights.llm import llm_enabled, rewrite_insights
from app.models.entities import (
    CategoryForecast,
    Dataset,
    ForecastDriver,
    ForecastMetric,
    ForecastPoint,
    ForecastRun,
    Insight,
    ModelCandidate,
    RegionalForecast,
)
from app.models.enums import (
    ForecastFrequency,
    ModelKind,
    PointKind,
    RunStatus,
)
from app.services import dataset_service
from app.services.job_runner import ProgressEvent, executors, progress_bus

logger = get_logger(__name__)

STAGES: tuple[tuple[str, float], ...] = (
    ("aggregating", 0.10),
    ("backtesting", 0.30),
    ("fitting", 0.75),
    ("persisting", 0.90),
    ("generating_insights", 0.96),
    ("complete", 1.0),
)

_run_overrides: dict[uuid.UUID, dict[str, object]] = {}


async def list_runs(session: AsyncSession, *, limit: int = 50) -> list[ForecastRun]:
    result = await session.execute(
        select(ForecastRun).order_by(ForecastRun.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


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
    frequency: ForecastFrequency | None = None,
    horizon: int | None = None,
    confidence_level: float = 0.8,
    max_folds: int | None = None,
    metric_weights: dict[str, float] | None = None,
    sarimax_order: list[int] | None = None,
    gbm_max_depth: int | None = None,
    llm_provider: str | None = None,
    llm_api_key: str | None = None,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
) -> ForecastRun:
    dataset = await dataset_service.get_dataset(session, dataset_id)

    if not dataset.parquet_path or not Path(dataset.parquet_path).exists():
        raise ValidationError(
            "This dataset has no stored data file. Re-upload it before forecasting."
        )

    resolved_time = time_column or dataset.time_column
    resolved_target = target_column or dataset.target_column
    resolved_frequency = frequency or dataset.frequency or ForecastFrequency.MONTHLY
    resolved_horizon = horizon or dataset.horizon or 6

    if not resolved_time:
        raise ValidationError(
            "No time column is configured. Select one before running a forecast."
        )
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
        frequency=resolved_frequency,
        horizon=resolved_horizon,
        confidence_level=confidence_level,
    )
    session.add(run)
    await session.flush()

    if any(
        opt is not None
        for opt in (
            max_folds,
            metric_weights,
            sarimax_order,
            gbm_max_depth,
            llm_provider,
            llm_api_key,
            llm_model,
            llm_base_url,
        )
    ):
        _run_overrides[run.id] = {
            "max_folds": max_folds,
            "metric_weights": metric_weights,
            "sarimax_order": sarimax_order,
            "gbm_max_depth": gbm_max_depth,
            "llm_provider": llm_provider,
            "llm_api_key": llm_api_key,
            "llm_model": llm_model,
            "llm_base_url": llm_base_url,
        }

    progress_bus.publish(
        ProgressEvent(
            run_id=run.id,
            status=RunStatus.PENDING,
            progress=0.0,
            stage="queued",
            message="Forecast queued.",
        )
    )
    return run


async def execute_run(run_id: uuid.UUID) -> None:
    try:
        await _execute(run_id)
    except Exception as exc:
        logger.exception("Forecast run %s failed", run_id)
        await _mark_failed(run_id, exc)


async def _execute(run_id: uuid.UUID) -> None:
    async with session_scope() as session:
        run = await get_run(session, run_id)
        dataset = await dataset_service.get_dataset(session, run.dataset_id)

        run.status = RunStatus.RUNNING
        run.started_at = utcnow()
        _advance(run, "aggregating", "Aggregating the series...")
        await session.flush()

        parquet_path = Path(dataset.parquet_path or "")
        payload = _build_payload(run, parquet_path)


    _publish(run_id, RunStatus.RUNNING, 0.30, "backtesting", "Backtesting candidate models...")

    try:
        output: ForecastOutput = await executors.run(run_forecast, payload)
    except InsufficientDataError as exc:
        raise ForecastError(str(exc)) from exc

    _publish(run_id, RunStatus.RUNNING, 0.90, "persisting", "Storing forecast results...")

    async with session_scope() as session:
        run = await get_run(session, run_id)
        await _persist_output(session, run, output)

        llm_config = _run_overrides.pop(run_id, None)
        _publish(
            run_id, RunStatus.RUNNING, 0.96, "generating_insights", "Generating insights..."
        )
        await _persist_insights(session, run, output, llm_config=llm_config)

        run.status = RunStatus.COMPLETED
        run.progress = 1.0
        run.stage = "complete"
        run.completed_at = utcnow()
        await session.flush()
        selected = run.selected_model.value if run.selected_model else None

    progress_bus.publish(
        ProgressEvent(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            progress=1.0,
            stage="complete",
            message="Forecast complete.",
            selected_model=selected,
        )
    )


def _build_payload(run: ForecastRun, parquet_path: Path) -> ForecastInput:
    series = queries.aggregate_series(
        parquet_path,
        run.time_column,
        run.target_column,
        run.frequency,
        weight_column=run.weight_column,
    )

    regions = _segments(parquet_path, run, run.region_column)
    categories = _segments(parquet_path, run, run.category_column)

    overrides = _run_overrides.pop(run.id, {})

    return ForecastInput(
        series=SeriesInput(
            periods=series.periods, values=series.values, weights=series.weights
        ),
        frequency=run.frequency,
        horizon=run.horizon,
        confidence_level=run.confidence_level,
        regions=regions,
        categories=categories,
        max_folds=overrides.get("max_folds"),
        metric_weights=overrides.get("metric_weights"),
        model_options={
            "sarimax_order": overrides.get("sarimax_order"),
            "gbm_max_depth": overrides.get("gbm_max_depth"),
        },
    )


def _segments(parquet_path: Path, run: ForecastRun, column: str | None) -> list[SegmentInput]:
    if not column:
        return []

    window = {
        ForecastFrequency.DAILY: 90,
        ForecastFrequency.WEEKLY: 26,
        ForecastFrequency.MONTHLY: 12,
        ForecastFrequency.QUARTERLY: 4,
    }[run.frequency]

    totals = queries.aggregate_segments(
        parquet_path,
        run.time_column,
        run.target_column,
        column,
        run.frequency,
        window_periods=window,
    )
    return [
        SegmentInput(
            label=t.label,
            current_total=t.current_total,
            prior_total=t.prior_total,
            series=t.series,
        )
        for t in totals
    ]


async def _persist_output(
    session: AsyncSession, run: ForecastRun, output: ForecastOutput
) -> None:
    await _clear_results(session, run.id)

    run.selected_model = ModelKind(output.selected_model)
    run.selection_rationale = output.selection_rationale
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
                mae=candidate["mae"],
                rmse=candidate["rmse"],
                smape=candidate["smape"],
                wmape=candidate["wmape"],
                score=candidate["score"],
                folds=int(candidate["folds"]),
                fit_seconds=candidate["fit_seconds"],
                params=candidate["params"],
                failed=bool(candidate["failed"]),
                failure_reason=candidate["failure_reason"],
            )
        )

    previous = await _previous_metrics(session, run)
    for name, value in output.metrics.items():
        session.add(
            ForecastMetric(
                run_id=run.id,
                name=name,
                value=float(value),
                unit=_metric_unit(name),
                previous_value=previous.get(name),
            )
        )


    for index, period in enumerate(output.history_periods):
        fitted = output.fitted_values[index] if index < len(output.fitted_values) else None
        session.add(
            ForecastPoint(
                run_id=run.id,
                period=period,
                kind=PointKind.ACTUAL,
                actual=output.history_values[index],
                forecast=fitted,
            )
        )

    for index, period in enumerate(output.forecast_periods):
        session.add(
            ForecastPoint(
                run_id=run.id,
                period=period,
                kind=PointKind.FORECAST,
                forecast=output.point_forecast[index],
                lower_bound=output.lower_bound[index],
                upper_bound=output.upper_bound[index],
                best_case=output.best_case[index],
                base_case=output.base_case[index],
                worst_case=output.worst_case[index],
            )
        )

    for segment in output.regions:
        session.add(
            RegionalForecast(
                run_id=run.id,
                region=segment.label,
                forecast_value=segment.forecast_value,
                prior_year_value=segment.prior_year_value,
                change_vs_last_year=segment.change_vs_last_year,
                accuracy=segment.accuracy,
                share=segment.share,
            )
        )

    for rank, segment in enumerate(output.categories, start=1):
        session.add(
            CategoryForecast(
                run_id=run.id,
                category=segment.label,
                forecast_value=segment.forecast_value,
                prior_year_value=segment.prior_year_value,
                share=segment.share,
                change_vs_last_year=segment.change_vs_last_year,
                accuracy=segment.accuracy,
                rank=rank,
            )
        )

    for rank, driver in enumerate(output.drivers, start=1):
        session.add(
            ForecastDriver(
                run_id=run.id,
                driver=driver.name,
                impact_value=driver.impact_value,
                impact_pct=driver.impact_pct,
                change_vs_last_year=driver.change_vs_last_year,
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

    rewritten = llm_enabled(llm_config)
    if rewritten:
        insights = rewrite_insights(insights, llm_config=llm_config)

    for rank, insight in enumerate(insights, start=1):
        session.add(
            Insight(
                run_id=run.id,
                type=insight.type,
                severity=insight.severity,
                title=insight.title,
                explanation=insight.explanation,
                suggested_action=insight.suggested_action,
                metric_name=insight.metric_name,
                metric_value=insight.metric_value,
                metric_unit=insight.metric_unit,
                supporting_data=insight.supporting_data,
                rank=rank,
                generated_at=insight.generated_at,
                llm_rewritten=rewritten,
            )
        )

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
    from sqlalchemy import delete

    for model in (
        ModelCandidate,
        ForecastMetric,
        ForecastPoint,
        RegionalForecast,
        CategoryForecast,
        ForecastDriver,
        Insight,
    ):
        await session.execute(delete(model).where(model.run_id == run_id))


def _metric_unit(name: str) -> str:
    if name in ("smape", "wmape", "accuracy", "seasonal_strength"):
        return "percent"
    if name in ("backtest_folds", "seasonal_period"):
        return "count"
    return "absolute"


def _looks_like_currency(column: str) -> bool:
    words = ("revenue", "sales", "amount", "value", "spend", "cost", "price", "gmv", "bookings")
    lowered = column.lower()
    return any(word in lowered for word in words)


def _advance(run: ForecastRun, stage: str, message: str) -> None:
    progress = dict(STAGES).get(stage, run.progress)
    run.stage = stage
    run.progress = progress
    _publish(run.id, RunStatus.RUNNING, progress, stage, message)


def _publish(
    run_id: uuid.UUID, status: RunStatus, progress: float, stage: str, message: str
) -> None:
    progress_bus.publish(
        ProgressEvent(
            run_id=run_id, status=status, progress=progress, stage=stage, message=message
        )
    )


async def _mark_failed(run_id: uuid.UUID, exc: Exception) -> None:
    message = getattr(exc, "message", None) or str(exc) or type(exc).__name__

    try:
        async with session_scope() as session:
            run = await get_run(session, run_id)
            run.status = RunStatus.FAILED
            run.stage = "failed"
            run.error_message = message[:2000]
            run.completed_at = utcnow()
            await session.flush()
    except Exception:
        logger.exception("Could not record failure for run %s", run_id)

    progress_bus.publish(
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
) -> list[ForecastPoint]:
    statement = select(ForecastPoint).where(ForecastPoint.run_id == run_id)
    if start is not None:
        statement = statement.where(ForecastPoint.period >= start)
    if end is not None:
        statement = statement.where(ForecastPoint.period <= end)

    result = await session.execute(statement.order_by(ForecastPoint.period, ForecastPoint.kind))
    return list(result.scalars().all())


async def dataset_for_run(session: AsyncSession, run: ForecastRun) -> Dataset:
    return await dataset_service.get_dataset(session, run.dataset_id)
