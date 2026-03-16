from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from app.models.db_models import Job, ModelResult
from app.schemas.forecast_schema import ForecastRequest

async def create_job_record(db: AsyncSession, job_id: str, user_id: str, request: ForecastRequest) -> Job:
    job = Job(
        id=job_id,
        user_id=user_id,
        name=request.name or "Forecast Job",
        status="queued",
        filename=request.filename,
        original_filename=request.original_filename,
        date_col=request.date_col,
        target_col=request.target_col,
        exog_cols=request.exog_cols,
        frequency=request.frequency,
        horizon=request.horizon,
        selected_models=request.selected_models,
        hyperparameters=request.hyperparameters,
        clean_anomalies=request.clean_anomalies,
        auto_tune=request.auto_tune,
        total_models=len(request.selected_models)
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job

async def get_job_by_id(db: AsyncSession, job_id: str) -> Job | None:
    result = await db.execute(select(Job).filter(Job.id == job_id))
    return result.scalars().first()

async def get_all_jobs(db: AsyncSession, user_id: str = "anonymous", limit: int = 200) -> list[Job]:
    """Return jobs for this user only, newest first, capped at limit rows."""
    result = await db.execute(
        select(Job)
        .filter(Job.user_id == user_id)
        .order_by(Job.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())

async def delete_job_record(db: AsyncSession, job_id: str):
    await db.execute(delete(Job).filter(Job.id == job_id))
    await db.commit()

async def update_job_status(db: AsyncSession, job_id: str, updates: dict):
    await db.execute(update(Job).where(Job.id == job_id).values(**updates))
    await db.commit()

async def get_model_results(db: AsyncSession, job_id: str) -> list[ModelResult]:
    result = await db.execute(select(ModelResult).filter(ModelResult.job_id == job_id).order_by(ModelResult.is_best.desc(), ModelResult.training_time.asc()))
    return list(result.scalars().all())

async def save_model_result(db: AsyncSession, job_id: str, model_name: str, result_data: dict):
    model_result = ModelResult(
        job_id=job_id,
        model_name=model_name,
        status=result_data.get("status", "completed"),
        metrics=result_data.get("metrics", {}),
        predictions=result_data.get("predictions", []),
        forecast=result_data.get("forecast", []),
        residuals=result_data.get("residuals", []),
        parameters=result_data.get("parameters", {}),
        tuning_metrics=result_data.get("tuning_metrics"),
        training_time=float(result_data.get("training_time", 0.0)),
        is_best=bool(result_data.get("is_best", False)),
        error=result_data.get("error")
    )
    db.add(model_result)
    await db.commit()
