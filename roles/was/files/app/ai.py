# app/ai.py
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

# ✅ 정확한 import (이게 핵심)
from db_ai import AsyncAISessionLocal


# ======================================================
# 1️⃣ 최종 선택 영상 저장
# ======================================================
async def insert_final_video(
    *,
    video_key: str,
    user_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
):
    async with AsyncAISessionLocal() as session:
        try:
            await session.execute(
                text("""
                    INSERT INTO ai_final_videos
                    (video_key, user_id, title, description)
                    VALUES (:video_key, :user_id, :title, :description)
                    ON CONFLICT (video_key)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description
                """),
                {
                    "video_key": video_key,
                    "user_id": user_id,
                    "title": title,
                    "description": description,
                }
            )
            await session.commit()

        except SQLAlchemyError as e:
            await session.rollback()
            raise RuntimeError(f"[ai] insert_final_video failed: {e}")



# ======================================================
# 2️⃣ YouTube 업로드 완료 처리
# ======================================================
async def mark_youtube_uploaded(
    *,
    video_key: str,
    youtube_video_id: str,
):
    async with AsyncAISessionLocal() as session:
        try:
            await session.execute(
                text("""
                    UPDATE ai_final_videos
                    SET
                        youtube_uploaded = TRUE,
                        youtube_video_id = :youtube_video_id,
                        youtube_uploaded_at = now()
                    WHERE video_key = :video_key
                """),
                {
                    "video_key": video_key,
                    "youtube_video_id": youtube_video_id,
                }
            )
            await session.commit()

        except SQLAlchemyError as e:
            await session.rollback()
            print(f"[WARN] mark_youtube_uploaded failed: {e}")


# ======================================================
# 3️⃣ 사용자 라이브러리 조회
# ======================================================
async def get_user_library(user_id: str) -> List[dict]:
    async with AsyncAISessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT
                    video_key,
                    title,
                    description,
                    youtube_uploaded,
                    youtube_video_id,
                    selected_at,
                    youtube_uploaded_at
                FROM ai_final_videos
                WHERE user_id = :user_id
                ORDER BY selected_at DESC
            """),
            {"user_id": user_id},
        )

        rows = result.mappings().all()
        return [dict(row) for row in rows]


# ======================================================
# 4️⃣ 운영 / 정책 로그 기록
# ======================================================
async def insert_operation_log(
    *,
    user_id: Optional[str],
    log_type: str,
    status: str,
    message: str,
    video_key: Optional[str] = None,
):
    async with AsyncAISessionLocal() as session:
        try:
            await session.execute(
                text("""
                    INSERT INTO ai_operation_logs
                    (user_id, log_type, status, video_key, message)
                    VALUES (:user_id, :log_type, :status, :video_key, :message)
                """),
                {
                    "user_id": user_id,
                    "log_type": log_type,
                    "status": status,
                    "video_key": video_key,
                    "message": message,
                }
            )
            await session.commit()

        except SQLAlchemyError as e:
            await session.rollback()
            print(f"[WARN] insert_operation_log failed: {e}")
