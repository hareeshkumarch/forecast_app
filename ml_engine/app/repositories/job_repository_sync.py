from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import Dict, Any
from app.models.db_models import Job, ModelResult

def update_job_status_sync(db: Session, job_id: str, updates: Dict[str, Any]) -> Job:
    job = db.execute(select(Job).filter(Job.id == job_id)).scalar_one_or_none()
    if not job:
        return None
    for k, v in updates.items():
        setattr(job, k, v)
    db.commit()
    db.refresh(job)
    return job

def save_model_result_sync(db: Session, job_id: str, model_name: str, result_data: Dict[str, Any]) -> ModelResult:
    res = db.execute(select(ModelResult).filter(ModelResult.job_id == job_id, ModelResult.model_name == model_name)).scalar_one_or_none()
    
    status = result_data.get("status", "failed")
    metrics = result_data.get("metrics")
    predictions = result_data.get("predictions")
    forecast = result_data.get("forecast")
    residuals = result_data.get("residuals")
    params = result_data.get("parameters")
    tuning_metrics = result_data.get("tuning_metrics")
    error = result_data.get("error")
    training_time = result_data.get("training_time")
    
    if res:
        res.status = status
        if metrics: res.metrics = metrics
        if predictions: res.predictions = predictions
        if forecast: res.forecast = forecast
        if residuals is not None: res.residuals = residuals
        if params: res.parameters = params
        if tuning_metrics is not None: res.tuning_metrics = tuning_metrics
        if error is not None: res.error = error
        if training_time is not None: res.training_time = training_time
    else:
        res = ModelResult(
            job_id=job_id,
            model_name=model_name,
            status=status,
            metrics=metrics,
            predictions=predictions,
            forecast=forecast,
            residuals=residuals,
            parameters=params,
            tuning_metrics=tuning_metrics,
            error=error,
            training_time=training_time
        )
        db.add(res)
    
    db.commit()
    return res
