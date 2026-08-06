from __future__ import annotations

from celery import Celery

from app.core.config import settings
from app.core.logging import configure_logging

FORECAST_QUEUE = "forecasts"

celery_app = Celery(
    "forecasting_platform",
    broker=settings.broker_url or None,
    backend=settings.result_backend or None,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_default_queue=FORECAST_QUEUE,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_soft_time_limit=settings.forecast_task_soft_time_limit,
    task_time_limit=settings.forecast_task_time_limit,
    result_expires=3_600,
    broker_connection_retry_on_startup=True,
)


@celery_app.on_after_configure.connect
def _configure_worker_logging(**_: object) -> None:
    configure_logging()
