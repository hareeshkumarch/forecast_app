from __future__ import annotations

import asyncio
import uuid
from typing import Any

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.core.logging import get_logger, request_id
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

RETRY_BACKOFF_SECONDS = 30


@celery_app.task(
    bind=True,
    name="forecasts.run",
    max_retries=settings.forecast_task_max_retries,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=RETRY_BACKOFF_SECONDS,
    retry_jitter=True,
)
def run_forecast_task(self: Task, run_id: str, correlation_id: str | None = None) -> dict[str, Any]:
    """
    Fits and persists one forecast run. Retries only transient infrastructure
    faults — a dataset that cannot be forecast is a permanent failure and is
    recorded on the run rather than retried.
    """
    from app.services import forecast_service

    token = request_id.set(correlation_id or self.request.id or "-")
    identifier = uuid.UUID(run_id)

    try:
        logger.info("Forecast run %s picked up (attempt %d)", identifier, self.request.retries + 1)
        status = asyncio.run(forecast_service.execute_run(identifier))
        return {"run_id": run_id, "status": status.value}
    except SoftTimeLimitExceeded:
        logger.error("Forecast run %s exceeded its time limit", identifier)
        asyncio.run(
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
