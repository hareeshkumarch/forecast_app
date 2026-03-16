from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ForecastRequest(BaseModel):
    name: Optional[str] = Field(None, description="Name of the forecast job")
    filename: str = Field(..., description="Uploaded secure file path identifier")
    original_filename: Optional[str] = None
    date_col: str
    target_col: str
    exog_cols: List[str] = []
    frequency: str = "auto"
    horizon: int = Field(30, ge=1, le=365)
    selected_models: List[str] = Field(default=["ARIMA", "Prophet", "LSTM"])
    clean_anomalies: bool = False
    auto_tune: bool = False
    hyperparameters: Dict[str, Any] = {}

class JobResponse(BaseModel):
    job_id: str
    status: str
    models_selected: List[str]
