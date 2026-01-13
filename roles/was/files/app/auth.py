from typing import Optional
from fastapi import APIRouter
from fastapi.responses import RedirectResponse
import secrets
from datetime import datetime, timedelta
from sqlalchemy import text

from config import *
from db import AsyncSessionLocal, redis_client
from utils import state_key, login_session_key, safe_redirect
from google import exchange_token, fetch_userinfo
from security import create_jwt

router = APIRouter(tags=["auth"])


# ======================================================
# 1. Google Login
# ======================================================
@router.get("/google/login")
async def google_login():
    state = secrets.token_urlsafe(16)
    redis_client.setex(state_key(state), STATE_TTL_SECONDS, "1")

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }

    from urllib.parse import urlencode
    return RedirectResponse(
        f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}",
        status_code=302,
    )


# ======================================================
# 2. Google Callback
# ======================================================
@router.get("/callback")
async def google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
):
    if not code or not state:
        return RedirectResponse(
            safe_redirect(FRONTEND_ERROR_URL, {"reason": "missing_param"})
        )

    # state 검증
    sk = state_key(state)
    if not redis_client.exists(sk):
        return RedirectResponse(
            safe_redirect(FRONTEND_ERROR_URL, {"reason": "invalid_state"})
        )
    redis_client.delete(sk)

    # ---- Google Token Exchange ----
    try:
        token_data = await exchange_token(
            {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI,
            }
        )
    except Exception:
        return RedirectResponse(
            safe_redirect(FRONTEND_ERROR_URL, {"reason": "token_fail"})
        )

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = int(token_data.get("expires_in", 3600))
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    if not access_token:
        return RedirectResponse(
            safe_redirect(FRONTEND_ERROR_URL, {"reason": "no_access_token"})
        )

    # ---- Userinfo ----
    try:
        userinfo = await fetch_userinfo(access_token)
    except Exception:
        return RedirectResponse(
            safe_redirect(FRONTEND_ERROR_URL, {"reason": "userinfo_fail"})
        )

    google_id = userinfo.get("id")
    email = userinfo.get("email")

    if not google_id or not email:
        return RedirectResponse(
            safe_redirect(FRONTEND_ERROR_URL, {"reason": "no_user"})
        )

    # ---- DB 처리 ----
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text("SELECT user_id FROM oauth_users WHERE google_id = :gid"),
            {"gid": google_id},
        )
        row = res.first()

        if row:
            user_id = row[0]
        else:
            user_id = secrets.token_hex(16)
            await db.execute(
                text("""
                    INSERT INTO oauth_users (user_id, google_id, email, created_at)
                    VALUES (:uid, :gid, :email, now())
                """),
                {"uid": user_id, "gid": google_id, "email": email},
            )

        await db.execute(
            text("""
                INSERT INTO oauth_tokens (user_id, access_token, refresh_token, expires_at)
                VALUES (:uid, :access, :refresh, :expires)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    expires_at = EXCLUDED.expires_at,
                    refresh_token = COALESCE(EXCLUDED.refresh_token, oauth_tokens.refresh_token)
            """),
            {
                "uid": user_id,
                "access": access_token,
                "refresh": refresh_token,
                "expires": expires_at,
            },
        )

        await db.commit()

    # ---- JWT 발급 ----
    jwt_token = create_jwt(user_id=user_id, email=email)

    sid = secrets.token_urlsafe(16)
    redis_client.setex(login_session_key(sid), LOGIN_SESSION_TTL_SECONDS, jwt_token)

    return RedirectResponse(
        safe_redirect(FRONTEND_SUCCESS_URL, {"sid": sid})
    )

# ======================================================
# 3. Login Session (1회용)
# ======================================================
@router.get("/session")
async def get_login_session(sid: str):
    token = redis_client.get(login_session_key(sid))
    if not token:
        raise HTTPException(status_code=401, detail="Session expired")

    # 1회용이므로 사용 후 삭제
    redis_client.delete(login_session_key(sid))

    return {
        "access_token": token,
        "token_type": "bearer",
    }
