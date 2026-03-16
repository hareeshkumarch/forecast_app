import json
from celery import Celery
import redis
# Need this setup before importing anything else
from app.core.config import settings

celery_app = Celery(
    "forecast_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)
celery_app.conf.update(
    worker_max_tasks_per_child=1
)

redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

from app.utils.converters import to_native

def publish_progress(job_id: str, payload: dict):
    try:
        # Deep convert to native types to ensure JSON serialization and DB safety
        clean_payload = to_native(payload)
        data = json.dumps(clean_payload)
        redis_client.publish(f"job_updates:{job_id}", data)
    except Exception as e:
        from app.core.logging import logger
        logger.error(f"Failed to publish progress for {job_id}: {e}")

@celery_app.task(name="run_training_pipeline", bind=True)
def run_training_pipeline(self, job_id: str, request_data: dict):
    from app.core.logging import logger
    logger.info(f"Starting pipeline for job {job_id}")
    publish_progress(job_id, {"type": "status", "status": "processing"})
    
    try:
        # NOTE: Heavy ML algorithms are run here natively inside the Celery worker process.
        # This prevents blocking the main Async API thread.
        import os
        import pandas as pd
        import sys
        
        # We load old preprocessor & models temporarily while phasing out
        sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from preprocessor import preprocess
        from models import MODEL_REGISTRY
        
        filename = request_data["filename"]
        date_col = request_data["date_col"]
        target_col = request_data["target_col"]
        exog_cols = request_data.get("exog_cols", [])
        frequency = request_data.get("frequency", "auto")
        horizon = request_data.get("horizon", 30)
        selected_models = request_data.get("selected_models", [])
        clean_anomalies = request_data.get("clean_anomalies", False)
        auto_tune = request_data.get("auto_tune", False)
        hyperparameters = request_data.get("hyperparameters", {})

        # Need to update DB synchronously since Celery is synchronous
        # Here we'll use a sync sessionmaker via SQLAlchemy or use an async wrapper. 
        # For simplicity, we can do API callbacks or async-to-sync calls for DB.
        publish_progress(job_id, {"type": "status", "status": "preprocessing", "message": "Preprocessing data..."})

        ext = os.path.splitext(filename)[1].lower()
        if ext == ".csv":
            df = pd.read_csv(filename)
        else:
            df = pd.read_excel(filename)

        df, prep_report = preprocess(df, date_col, target_col, exog_cols, frequency, clean_anomalies)
        
        # Notify WebSocket
        publish_progress(job_id, {"type": "preprocessing", "report": prep_report})
        # Need to update DB synchronously since Celery is synchronous.
        # Use simple synchronous db sessions to prevent connection exhaustion.
        from app.database.session import SessionLocal
        from app.repositories.job_repository_sync import update_job_status_sync, save_model_result_sync
        
        def _update_db_prep_sync():
            with SessionLocal() as db:
                update_job_status_sync(db, job_id, {"preprocessing_report": to_native(prep_report), "status": "training"})
                
        try:
            _update_db_prep_sync()
        except Exception as e:
            logger.error(f"Failed to save prep report sync: {e}")
        
        publish_progress(job_id, {"type": "status", "status": "training"})
        
        # Execute models sequentially 
        successful_results = []
        for i, model_name in enumerate(selected_models):
            if model_name == "Ensemble":
                continue

            if model_name not in MODEL_REGISTRY:
                publish_progress(job_id, {"type": "model_error", "model": model_name, "error": f"Unknown model: {model_name}"})
                continue
                
            publish_progress(job_id, {
                "type": "model_start", 
                "model": model_name, 
                "index": i, 
                "total": len(selected_models),
                "completed_count": i,
                "currently_training": model_name
            })
            
            def progress_cb(progress, message, live_metrics=None, _name=model_name, _i=i):
                publish_progress(job_id, {
                    "type": "model_progress",
                    "model": _name,
                    "progress": progress,
                    "message": message,
                    "live_metrics": live_metrics,
                    "completed_count": _i,
                    "currently_training": _name
                })
            
            try:
                # Wrap long running models
                result = MODEL_REGISTRY[model_name](
                    df, date_col, target_col, horizon,
                    exog_cols=exog_cols,
                    progress_cb=progress_cb,
                    hyperparameters=hyperparameters,
                    auto_tune=auto_tune
                )
                result["status"] = "completed"
                result["model_name"] = model_name
                successful_results.append(result)

                def _save_model_db_sync(_r=result, _name=model_name, _i=i):
                    with SessionLocal() as db:
                        save_model_result_sync(db, job_id, _name, to_native(_r))
                        update_job_status_sync(db, job_id, {"completed_models": _i + 1})

                try:
                    _save_model_db_sync()
                except Exception as e:
                    logger.error(f"DB Error saving model {model_name}: {e}")
                
                publish_progress(job_id, {
                    "type": "model_complete",
                    "model": model_name,
                    "metrics": result["metrics"],
                    "training_time": result["training_time"],
                    "index": i,
                    "total": len(selected_models),
                    "completed_count": i + 1,
                    "currently_training": None
                })
            except Exception as e:
                import traceback
                error_msg = str(e)
                tb = traceback.format_exc()
                logger.error(f"Error training {model_name}: {error_msg}\n{tb}")
                
                def _save_error_db_sync(_err=error_msg, _name=model_name, _i=i):
                    with SessionLocal() as db:
                        save_model_result_sync(db, job_id, _name, {"status": "failed", "error": _err})
                        update_job_status_sync(db, job_id, {"completed_models": _i + 1})
                        
                try:
                    _save_error_db_sync()
                except Exception as e:
                    pass
                publish_progress(job_id, {
                    "type": "model_error", 
                    "model": model_name, 
                    "error": error_msg,
                    "completed_count": i + 1,
                    "currently_training": None
                })
                
        # Final best model resolution missing here but standard implementation applies

        if "Ensemble" in selected_models and len(successful_results) > 1:
            publish_progress(job_id, {
                "type": "model_start", 
                "model": "Ensemble", 
                "index": len(selected_models)-1, 
                "total": len(selected_models),
                "completed_count": len(selected_models)-1,
                "currently_training": "Ensemble"
            })
            successful_results.sort(key=lambda x: x["metrics"].get("rmse", float('inf')))
            top_models = successful_results[:3]
            
            import copy
            ens_preds = copy.deepcopy(top_models[0]["predictions"])
            ens_fc = copy.deepcopy(top_models[0]["forecast"])
            
            # Average predictions
            for idx in range(len(ens_preds)):
                vals = [m["predictions"][idx].get("predicted") for m in top_models if idx < len(m["predictions"]) and m["predictions"][idx].get("predicted") is not None]
                if vals: ens_preds[idx]["predicted"] = sum(vals)/len(vals)
                
            # Average forecast
            for idx in range(len(ens_fc)):
                vals = [m["forecast"][idx].get("predicted") for m in top_models if idx < len(m["forecast"]) and m["forecast"][idx].get("predicted") is not None]
                if vals: ens_fc[idx]["predicted"] = sum(vals)/len(vals)
                
                lowers = [m["forecast"][idx].get("lower") for m in top_models if idx < len(m["forecast"]) and m["forecast"][idx].get("lower") is not None]
                if lowers: ens_fc[idx]["lower"] = sum(lowers)/len(lowers)
                
                uppers = [m["forecast"][idx].get("upper") for m in top_models if idx < len(m["forecast"]) and m["forecast"][idx].get("upper") is not None]
                if uppers: ens_fc[idx]["upper"] = sum(uppers)/len(uppers)

            ensemble_result = {
                "status": "completed",
                "model_name": "Ensemble",
                "predictions": ens_preds,
                "forecast": ens_fc,
                "parameters": {"top_models": [m["model_name"] for m in top_models]},
                "training_time": 0.1
            }
            
            # FIX Bug 17: Compute real Ensemble metrics from averaged predictions vs actuals
            try:
                import numpy as _np
                ens_actual = _np.array([p.get("actual") for p in ens_preds if p.get("actual") is not None and p.get("predicted") is not None], dtype=float)
                ens_pred_vals = _np.array([p.get("predicted") for p in ens_preds if p.get("actual") is not None and p.get("predicted") is not None], dtype=float)
                if len(ens_actual) > 0 and len(ens_pred_vals) > 0:
                    ens_mae = float(_np.mean(_np.abs(ens_actual - ens_pred_vals)))
                    ens_rmse = float(_np.sqrt(_np.mean((ens_actual - ens_pred_vals) ** 2)))
                    nonzero = ens_actual != 0
                    ens_mape = float(_np.mean(_np.abs((ens_actual[nonzero] - ens_pred_vals[nonzero]) / ens_actual[nonzero])) * 100) if nonzero.sum() > 0 else None
                    ss_res = _np.sum((ens_actual - ens_pred_vals) ** 2)
                    ss_tot = _np.sum((ens_actual - _np.mean(ens_actual)) ** 2)
                    ens_r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else None
                    ens_metrics = {"mae": round(ens_mae, 4), "rmse": round(ens_rmse, 4),
                                   "mape": round(ens_mape, 4) if ens_mape is not None else None,
                                   "r2": round(ens_r2, 4) if ens_r2 is not None else None}
                    # FIX Bug 18: Compute Ensemble residuals
                    ens_residuals_vals = list(ens_actual - ens_pred_vals)
                else:
                    ens_metrics = top_models[0]["metrics"]
                    ens_residuals_vals = []
            except Exception:
                ens_metrics = top_models[0]["metrics"]
                ens_residuals_vals = []
            
            ensemble_result["metrics"] = ens_metrics
            ensemble_result["residuals"] = [float(r) for r in ens_residuals_vals]
            
            def _save_ens_sync():
                with SessionLocal() as db:
                    save_model_result_sync(db, job_id, "Ensemble", to_native(ensemble_result))
                    update_job_status_sync(db, job_id, {"completed_models": len(selected_models)})
            try: _save_ens_sync()
            except Exception: pass
            
            publish_progress(job_id, {
                "type": "model_complete",
                "model": "Ensemble",
                "metrics": ensemble_result["metrics"],
                "training_time": 0.1,
                "index": len(selected_models)-1,
                "total": len(selected_models),
                "completed_count": len(selected_models),
                "currently_training": None
            })

        def _finish_job_sync():
            with SessionLocal() as db:
                from sqlalchemy import select
                from app.models.db_models import ModelResult
                res = db.execute(select(ModelResult).filter(ModelResult.job_id == job_id, ModelResult.status == "completed"))
                completed = list(res.scalars().all())
                if completed:
                    def get_rmse(m):
                        try:
                            return m.metrics.get("rmse", float('inf')) if m.metrics else float('inf')
                        except Exception:
                            return float('inf')
                    best = min(completed, key=get_rmse)
                    best.is_best = True
                    db.commit()
                update_job_status_sync(db, job_id, {"status": "completed"})

       
        # FIX Bug 20: Replace bare except: pass with proper logging so failures surface
        try: _finish_job_sync()
        except Exception as finish_err:
            logger.error(f"Failed to finish job {job_id}: {finish_err}")

        publish_progress(job_id, {"type": "complete", "message": "All models finished"})
        logger.info(f"Job {job_id} completed successfully.")
        
    except Exception as e:
        logger.error(f"Job {job_id} failed", exc_info=True)
        import traceback
        tb = traceback.format_exc()
        error_msg = str(e)
        
        def _fail_job_sync():
            with SessionLocal() as db:
                update_job_status_sync(db, job_id, {"status": "failed", "error": error_msg})

        try:
            _fail_job_sync()
        except Exception as inner_e:
            logger.error(f"Failed to update job {job_id} failure status: {inner_e}")
            
        publish_progress(job_id, {"type": "error", "error": str(e), "traceback": tb})
