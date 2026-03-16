from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from app.database.session import Base

class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, default="anonymous")
    name = Column(String, nullable=False)
    status = Column(String, default="pending")
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=True)
    date_col = Column(String, nullable=False)
    target_col = Column(String, nullable=False)
    exog_cols = Column(JSON, default=list)
    frequency = Column(String, default="auto")
    horizon = Column(Integer, default=30)
    selected_models = Column(JSON, default=list)
    clean_anomalies = Column(Boolean, default=False)
    hyperparameters = Column(JSON, default=dict)
    auto_tune = Column(Boolean, default=False)
    preprocessing_report = Column(JSON, default=dict)
    total_models = Column(Integer, default=0)
    completed_models = Column(Integer, default=0)
    error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

class ModelResult(Base):
    __tablename__ = "model_results"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    model_name = Column(String, nullable=False)
    status = Column(String, default="pending")
    metrics = Column(JSON, default=dict)
    predictions = Column(JSON, default=list)
    forecast = Column(JSON, default=list)
    residuals = Column(JSON, default=list)
    parameters = Column(JSON, default=dict)
    tuning_metrics = Column(JSON, nullable=True)
    training_time = Column(Float, default=0.0)
    is_best = Column(Boolean, default=False)
    error = Column(String, nullable=True)
