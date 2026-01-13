from fastapi import APIRouter
from sqlalchemy import text
from db import engine, redis_client

router = APIRouter()

@router.get("/health")
async def health():
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    redis_client.ping()
    return {"status": "ok"}
