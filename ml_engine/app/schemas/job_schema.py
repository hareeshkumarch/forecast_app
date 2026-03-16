from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime

class JobDetailResponse(BaseModel):
    id: str
    name: str
    status: str
    filename: str
    original_filename: Optional[str] = None
    date_col: str
    target_col: str
    exog_cols: List[str] = []
    frequency: str
    horizon: int
    selected_models: List[str] = []
    hyperparameters: Dict[str, Any] = {}
    clean_anomalies: bool
    preprocessing_report: Dict[str, Any] = {}
    total_models: int
    completed_models: int
    error: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
