import os

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

REDIS_HOST = os.getenv("REDIS_HOST", "10.1.1.5")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

STATE_TTL_SECONDS = int(os.getenv("STATE_TTL_SECONDS", "300"))
LOGIN_SESSION_TTL_SECONDS = int(os.getenv("LOGIN_SESSION_TTL_SECONDS", "120"))

FRONTEND_SUCCESS_URL = os.getenv(
    "FRONTEND_SUCCESS_URL", "https://justic.store/login/success"
)
FRONTEND_ERROR_URL = os.getenv(
    "FRONTEND_ERROR_URL", "https://justic.store/login/error"
)

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

DB_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# =========================
# AI DB 설정
# =========================
AI_DB_USER = os.getenv("AI_DB_USER")
AI_DB_PASSWORD = os.getenv("AI_DB_PASSWORD")
AI_DB_HOST = os.getenv("AI_DB_HOST")
AI_DB_PORT = os.getenv("AI_DB_PORT", "5432")
AI_DB_NAME = os.getenv("AI_DB_NAME")

AI_DB_URL = (
    f"postgresql+asyncpg://{AI_DB_USER}:{AI_DB_PASSWORD}"
    f"@{AI_DB_HOST}:{AI_DB_PORT}/{AI_DB_NAME}"
)