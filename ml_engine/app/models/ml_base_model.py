import time
import numpy as np
from abc import ABC, abstractmethod

class BaseModelAdapter(ABC):
    def __init__(self, hyperparameters: dict = None, progress_cb=None):
        self.hyperparameters = hyperparameters or {}
        self.progress_cb = progress_cb
        self.training_time = 0.0

    @abstractmethod
    def fit_and_predict(self, df, date_col, target_col, horizon, exog_cols=None):
        """Must return a tuple: (dates, actual, fitted, fc_dates, fc_vals, lower, upper, residuals, params)"""
        pass

    def compute_metrics(self, actual: np.ndarray, predicted: np.ndarray, aic=None, bic=None) -> dict:
        mask = ~(np.isnan(actual) | np.isnan(predicted))
        a, p = actual[mask], predicted[mask]
        if len(a) == 0:
            return {"mae": None, "rmse": None, "mape": None, "r2": None}
        mae = float(np.mean(np.abs(a - p)))
        rmse = float(np.sqrt(np.mean((a - p) ** 2)))
        mape = float(np.mean(np.abs((a - p) / (a + 1e-10))) * 100)
        ss_res = np.sum((a - p) ** 2)
        ss_tot = np.sum((a - np.mean(a)) ** 2)
        r2 = float(1 - ss_res / (ss_tot + 1e-10))
        m = {"mae": round(mae, 4), "rmse": round(rmse, 4), "mape": round(mape, 4), "r2": round(r2, 4)}
        if aic is not None:
            m["aic"] = round(aic, 4)
        if bic is not None:
            m["bic"] = round(bic, 4)
        return m

    def execute(self, df, date_col, target_col, horizon, exog_cols=None):
        t0 = time.time()
        dates, actual, fitted, fc_dates, fc_vals, lower, upper, residuals, params = self.fit_and_predict(
            df, date_col, target_col, horizon, exog_cols
        )
        self.training_time = time.time() - t0
        metrics = self.compute_metrics(actual, fitted)
        
        def safe_float(v):
            if v is None: return None
            if isinstance(v, (np.integer,)): return int(v)
            if isinstance(v, (np.floating,)):
                v = float(v)
                if np.isnan(v) or np.isinf(v): return None
                return v
            return v
        
        return {
            "metrics": metrics,
            "predictions": [{"date": str(d), "actual": safe_float(a), "predicted": safe_float(p)} for d, a, p in zip(dates, actual, fitted)],
            "forecast": [{"date": str(d), "predicted": safe_float(p), "lower": safe_float(l), "upper": safe_float(u)} for d, p, l, u in zip(fc_dates, fc_vals, lower or [None]*len(fc_vals), upper or [None]*len(fc_vals))],
            "residuals": [safe_float(r) for r in residuals] if residuals is not None else [],
            "parameters": {k: safe_float(v) if isinstance(v, (int, float, np.integer, np.floating)) else str(v) for k, v in (params or {}).items()},
            "training_time": round(self.training_time, 3),
        }
