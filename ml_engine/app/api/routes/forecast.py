from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.forecast_schema import ForecastRequest, JobResponse
from app.database.session import get_db
from app.repositories.job_repository import create_job_record
from app.core.security import get_current_user_optional
from app.core.logging import logger
from app.workers.celery_worker import run_training_pipeline
import uuid
import os

router = APIRouter()

# Must match keys in MODEL_REGISTRY (models.py)
VALID_MODEL_IDS = {"ARIMA", "SARIMA", "ARIMAX", "Prophet", "Holt-Winters", "Random Forest", "XGBoost", "LSTM", "Transformer"}

@router.post("", response_model=JobResponse)
async def start_forecast(
    request: ForecastRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user_optional)
):
    # Validate required fields
    if not request.filename or not request.date_col or not request.target_col:
        raise HTTPException(400, "filename, date_col, and target_col are required")

    # Validate file exists on server
    if not os.path.exists(request.filename):
        raise HTTPException(400, f"Uploaded file not found on server. Please re-upload your data.")

    # Validate selected models against known registry
    if not request.selected_models:
        raise HTTPException(400, "At least one model must be selected")

    unknown_models = [m for m in request.selected_models if m not in VALID_MODEL_IDS]
    if unknown_models:
        raise HTTPException(400, f"Unknown model(s): {unknown_models}. Valid options: {sorted(VALID_MODEL_IDS)}")

    job_id = f"job_{uuid.uuid4().hex[:8]}"

    try:
        await create_job_record(db, job_id, current_user["user_id"], request)
    except Exception as e:
        logger.error(f"Failed to create job record for {job_id}: {e}", exc_info=True)
        raise HTTPException(500, "Failed to create job. Please try again.")

    # Dispatch Celery background task
    run_training_pipeline.delay(job_id, request.model_dump())

    return JobResponse(job_id=job_id, status="queued", models_selected=request.selected_models)
