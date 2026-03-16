import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "ForecastHub ML Engine"
    VERSION: str = "3.0"
    API_V1_STR: str = "/api/v1"
    
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/data/forecast.db")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    UPLOAD_DIRECTORY: str = os.getenv("UPLOAD_DIRECTORY", "/app/uploads")
    MAX_TRAINING_TIMEOUT_SEC: int = int(os.getenv("MAX_TRAINING_TIMEOUT_SEC", 300))
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5000").split(",")
    
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "local") # local or s3

    class Config:
        env_file = ".env"

settings = Settings()
