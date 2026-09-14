from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from typing import Any, TypeVar

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.core.logging import get_logger, request_id
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

RETRY_BACKOFF_SECONDS = 30

T = TypeVar("T")


def _run(work: Coroutine[Any, Any, T]) -> T:
    # Progress reaches Redis from a sender thread, so the last frame of a run is
    # still in flight when the body returns; asyncio.run would cancel it.
    from app.services.job_runner import flush_channel_publishes

    async def until_delivered() -> T:
        try:
            return await work
        finally:
            await flush_channel_publishes()

    return asyncio.run(until_delivered())


@celery_app.task(
    bind=True,
    name="forecasts.run",
    max_retries=settings.forecast_task_max_retries,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=RETRY_BACKOFF_SECONDS,
    retry_jitter=True,
)
def run_forecast_task(self: Task, run_id: str, correlation_id: str | None = None) -> dict[str, Any]:
    from app.services import forecast_service

    token = request_id.set(correlation_id or self.request.id or "-")
    identifier = uuid.UUID(run_id)

    try:
        logger.info("Forecast run %s picked up (attempt %d)", identifier, self.request.retries + 1)
        status = _run(forecast_service.execute_run(identifier))
        return {"run_id": run_id, "status": status.value}
    except SoftTimeLimitExceeded:
        logger.error("Forecast run %s exceeded its time limit", identifier)
        _run(
            forecast_service.mark_failed(
                identifier,
                TimeoutError(
                    "The forecast took longer than the configured limit. "
                    "Try a shorter horizon or fewer validation folds."
                ),
            )
        )
        return {"run_id": run_id, "status": "failed", "reason": "time_limit"}
    finally:
        request_id.reset(token)


@celery_app.task(bind=True, name="forecasts.fit_series")
def fit_series_task(
    self: Task, job: dict[str, Any], correlation_id: str | None = None
) -> list[dict[str, Any]]:
    from app.services import series_service

    token = request_id.set(correlation_id or self.request.id or "-")
    try:
        return series_service.run_chunk_job(job)
    except SoftTimeLimitExceeded:
        logger.error("A series chunk for run %s exceeded its time limit", job.get("run_id"))
        return series_service.blocked_chunk(job, "Fitting this series ran out of time.")
    except Exception as exc:
        logger.exception("A series chunk for run %s failed", job.get("run_id"))
        return series_service.blocked_chunk(job, f"{type(exc).__name__}: {exc}")
    finally:
        request_id.reset(token)


@celery_app.task(bind=True, name="forecasts.finalise_series")
def finalise_series_task(
    self: Task,
    chunks: list[list[dict[str, Any]]],
    run_id: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    from app.forecasting.engine import LeafFit
    from app.services import forecast_service, series_service

    token = request_id.set(correlation_id or self.request.id or "-")
    identifier = uuid.UUID(run_id)

    try:
        fits = [LeafFit.from_dict(row) for chunk in chunks for row in chunk]
        logger.info("Run %s collecting %d fitted series", identifier, len(fits))
        status = _run(series_service.finalise(identifier, fits))
        return {"run_id": run_id, "status": status.value, "series": len(fits)}
    except Exception as exc:
        logger.exception("Could not finalise grouped run %s", identifier)
        _run(forecast_service.mark_failed(identifier, exc))
        return {"run_id": run_id, "status": "failed"}
    finally:
        request_id.reset(token)
