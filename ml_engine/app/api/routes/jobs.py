from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.repositories import job_repository
from app.schemas.job_schema import JobDetailResponse
from app.core.security import get_current_user_optional
from app.core.logging import logger
import os

router = APIRouter()

@router.get("", response_model=list[JobDetailResponse])
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user_optional)
):
    # Filter by user_id so each user only sees their own jobs
    jobs = await job_repository.get_all_jobs(db, user_id=current_user["user_id"])
    return jobs

@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user_optional)
):
    job = await job_repository.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

# NOTE: /results/{job_id} MUST be registered BEFORE /{job_id} to avoid FastAPI
# matching "results" as a job_id in the /{job_id} route.
@router.get("/results/{job_id}")
async def get_results(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user_optional)
):
    job = await job_repository.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    results = await job_repository.get_model_results(db, job_id)

    return {
        "job": job,
        "status": job.status,
        "preprocessing": job.preprocessing_report,
        "results": results
    }

@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user_optional)
):
    job = await job_repository.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Delete uploaded file from disk (prevents disk leak)
    if job.filename and os.path.isfile(job.filename):
        try:
            os.remove(job.filename)
            logger.info(f"Deleted uploaded file for job {job_id}: {job.filename}")
        except OSError as e:
            logger.warning(f"Could not delete file {job.filename} for job {job_id}: {e}")

    await job_repository.delete_job_record(db, job_id)
    return {"deleted": True, "job_id": job_id}
