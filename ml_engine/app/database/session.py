from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine
from app.core.config import settings

# Since SQLite does not support standard pool settings like pool_size effectively, we need conditional arguments
if settings.DATABASE_URL.startswith("sqlite"):
    engine = create_async_engine(settings.DATABASE_URL, echo=False, connect_args={"timeout": 30})
else:
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=20, max_overflow=10)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# Synchronous engine for Celery worker
sync_db_url = settings.DATABASE_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
if sync_db_url.startswith("sqlite"):
    sync_engine = create_engine(sync_db_url, echo=False, connect_args={"check_same_thread": False, "timeout": 30})
else:
    sync_engine = create_engine(sync_db_url, echo=False, pool_size=20, max_overflow=10)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
