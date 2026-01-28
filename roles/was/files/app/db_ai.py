# app/db_ai.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from config import AI_DB_URL

ai_engine = create_async_engine(
    AI_DB_URL,
    pool_size=10,          # 🔥 기본 5 → 10
    max_overflow=20,       # 🔥 기본 10 → 20
    pool_recycle=1800,     # 🔥 30분
    pool_pre_ping=True,
)

AsyncAISessionLocal = sessionmaker(
    ai_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)
