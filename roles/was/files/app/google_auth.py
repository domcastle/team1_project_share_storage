# app/google_auth.py
import os
from datetime import timezone

from sqlalchemy import text
from sqlalchemy import create_engine

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import DB_URL

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
]

# ======================================================
# 🔥 동기 DB 엔진 (YouTube 전용)
# ======================================================
sync_engine = create_engine(
    DB_URL.replace("+asyncpg", ""),  # async 제거
    pool_pre_ping=True,
)

# ======================================================
# 기존 로그인 로직 (유지)
# ======================================================
import httpx

async def exchange_token(data: dict) -> dict:
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_userinfo(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()

# ======================================================
# 🔥 YouTube 업로드용 (SYNC, 핵심)
# ======================================================
def get_youtube_service(user_id: str):
    with sync_engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT access_token, refresh_token, expires_at
                FROM oauth_tokens
                WHERE user_id = :uid
            """),
            {"uid": user_id},
        ).fetchone()

    if not row:
        raise Exception("Google OAuth token not found")

    access_token, refresh_token, expires_at = row

    # ✅ 여기만 수정됨 (timezone 처리)
    expiry = None
    if expires_at:
        if expires_at.tzinfo is None:
            expiry = expires_at.replace(tzinfo=timezone.utc)
        else:
            expiry = expires_at

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=GOOGLE_TOKEN_URL,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=YOUTUBE_SCOPES,
    )

    return build(
        "youtube",
        "v3",
        credentials=creds,
        cache_discovery=False,
    )
