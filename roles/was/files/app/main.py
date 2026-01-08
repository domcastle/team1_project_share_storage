import os
import secrets
import jwt
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
import redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from urllib.parse import urlencode

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError, OperationalError

# ======================================================
# Logging
# ======================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auth-server")

# ======================================================
# App
# ======================================================
app = FastAPI(title="Auth Server", version="1.2")

# ======================================================
# Environment Variables
# ======================================================
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Redis (CSRF state 공유용)
REDIS_HOST = os.getenv("REDIS_HOST", "10.1.1.5")  # 너네 Redis: 10.1.1.5
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")  # 없으면 None
STATE_TTL_SECONDS = int(os.getenv("STATE_TTL_SECONDS", "300"))  # state 유효기간 5분

# ======================================================
# Google OAuth URLs
# ======================================================
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# ======================================================
# DB Engine
# - connect_timeout(초)로 "DB 붙다 멈춤" 방지 (504 예방)
# ======================================================
engine = None
if DB_HOST and DB_NAME and DB_USER and DB_PASSWORD:
    DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    try:
        engine = create_engine(
            DB_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_timeout=5,
            connect_args={"connect_timeout": 3},  # ★ 중요: DB 연결 3초 내 실패
        )
        logger.info("DB engine configured.")
    except Exception as e:
        engine = None
        logger.exception("Failed to configure DB engine: %s", e)

# ======================================================
# Redis Client (CSRF State Store)
# ======================================================
redis_client: Optional[redis.Redis] = None
try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        retry_on_timeout=True,
    )
    # ping 테스트
    redis_client.ping()
    logger.info("Redis configured: %s:%s db=%s", REDIS_HOST, REDIS_PORT, REDIS_DB)
except Exception as e:
    redis_client = None
    logger.exception("Redis is not available: %s", e)

def _state_key(state: str) -> str:
    return f"oauth_state:{state}"

def require_redis():
    if redis_client is None:
        # 이중화 목적이면 Redis 없을 때는 실패시키는 게 맞음
        raise HTTPException(status_code=503, detail="Redis is not configured")

# ======================================================
# Shared HTTPX client (성능 + 연결 재사용)
# ======================================================
http_client: Optional[httpx.AsyncClient] = None

@app.on_event("startup")
async def startup():
    global http_client
    http_client = httpx.AsyncClient(timeout=5.0)

@app.on_event("shutdown")
async def shutdown():
    global http_client
    if http_client:
        await http_client.aclose()
        http_client = None

def require_http_client():
    if http_client is None:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

# ======================================================
# Health
# ======================================================
@app.get("/")
def root():
    return {"message": "Auth server is running"}

@app.get("/health")
def health():
    return {
        "status": "ok",
        "db_configured": engine is not None,
        "redis_configured": redis_client is not None,
    }

# ======================================================
# 1. Google Login
# ======================================================
@app.get("/auth/google/login")
def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth environment variables are not configured",
        )

    # ★ 이중화 목적이면 state는 반드시 Redis에 저장해야 함
    require_redis()

    state = secrets.token_urlsafe(16)

    try:
        # state 1회성 + TTL (5분)
        redis_client.setex(_state_key(state), STATE_TTL_SECONDS, "1")
    except Exception as e:
        logger.exception("Failed to save state to Redis: %s", e)
        raise HTTPException(status_code=503, detail="Failed to store CSRF state")

    scope = "openid email profile https://www.googleapis.com/auth/youtube.upload"

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }

    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(auth_url, status_code=307)

# ======================================================
# 2. Google Callback (async + httpx)
# ======================================================
@app.get("/auth/callback")
async def google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
):
    logger.info("CALLBACK ENTERED code=%s state=%s", "YES" if code else "NO", state)

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Google OAuth env is missing")

    require_http_client()
    require_redis()

    # ==================================================
    # CSRF state 검증 (Redis)
    # - callback이 WAS2로 와도 통과해야 하므로 공유 저장소 필수
    # ==================================================
    key = _state_key(state)
    try:
        exists = redis_client.exists(key)
        if not exists:
            raise HTTPException(status_code=400, detail="Invalid or expired CSRF state")
        # 1회성 처리
        redis_client.delete(key)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Redis state check failed: %s", e)
        raise HTTPException(status_code=503, detail="CSRF state validation failed")

    # ==================================================
    # 3. Google Token Exchange
    # ==================================================
    try:
        logger.info("TOKEN EXCHANGE START")
        token_resp = await http_client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        logger.info("TOKEN EXCHANGE DONE status=%s", token_resp.status_code)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Google token exchange timed out")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Google token exchange failed: {e}")

    if token_resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Google token exchange failed: {token_resp.text}",
        )

    token_data = token_resp.json()
    google_access_token = token_data.get("access_token")
    google_refresh_token = token_data.get("refresh_token")

    if not google_access_token:
        raise HTTPException(status_code=400, detail="No access token from Google")

    # ==================================================
    # 4. Google User Info
    # ==================================================
    try:
        logger.info("USERINFO START")
        userinfo_resp = await http_client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {google_access_token}"},
        )
        logger.info("USERINFO DONE status=%s", userinfo_resp.status_code)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Google userinfo request timed out")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Google userinfo request failed: {e}")

    if userinfo_resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch user info: {userinfo_resp.text}",
        )

    userinfo = userinfo_resp.json()
    google_id = userinfo.get("id")
    email = userinfo.get("email")

    if not google_id or not email:
        raise HTTPException(status_code=400, detail="Invalid user info")

    # ==================================================
    # 5. DB Mapping
    # ==================================================
    if engine is None:
        # DB 미정이면 여기서 빠르게 503으로 떨어져야 정상 (504 방지)
        raise HTTPException(status_code=503, detail="DB is not configured")

    try:
        logger.info("DB MAPPING START google_id=%s email=%s", google_id, email)
        with engine.begin() as conn:
            result = conn.execute(
                text("SELECT id FROM users WHERE google_id = :gid"),
                {"gid": google_id},
            ).fetchone()

            if result:
                user_db_id = result.id
                conn.execute(
                    text("UPDATE users SET updated_at = NOW() WHERE id = :id"),
                    {"id": user_db_id},
                )
            else:
                result = conn.execute(
                    text("""
                        INSERT INTO users (google_id, email)
                        VALUES (:gid, :email)
                        RETURNING id
                    """),
                    {"gid": google_id, "email": email},
                )
                user_db_id = result.fetchone().id

            if google_refresh_token:
                conn.execute(
                    text("""
                        INSERT INTO oauth_tokens (user_id, provider, refresh_token)
                        VALUES (:uid, 'google', :rt)
                        ON CONFLICT (user_id, provider)
                        DO UPDATE SET
                            refresh_token = EXCLUDED.refresh_token,
                            created_at = NOW()
                    """),
                    {"uid": user_db_id, "rt": google_refresh_token},
                )

        logger.info("DB MAPPING DONE user_id=%s", user_db_id)

    except OperationalError as e:
        logger.exception("DB operational error: %s", e)
        raise HTTPException(status_code=503, detail="DB connection failed")
    except SQLAlchemyError as e:
        logger.exception("DB error: %s", e)
        raise HTTPException(status_code=500, detail="DB error")
    except Exception as e:
        logger.exception("Unexpected DB mapping error: %s", e)
        raise HTTPException(status_code=500, detail="Unexpected error")

    # ==================================================
    # 6. JWT Issuance
    # ==================================================
    now = datetime.utcnow()
    payload = {
        "sub": str(user_db_id),
        "email": email,
        "iss": "onprem-auth-server",
        "aud": "onprem-video-platform",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=JWT_EXPIRE_MINUTES)).timestamp()),
    }

    jwt_token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    return JSONResponse(
        {
            "access_token": jwt_token,
            "token_type": "bearer",
            "expires_in": JWT_EXPIRE_MINUTES * 60,
        }
    )