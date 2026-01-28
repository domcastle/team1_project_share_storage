# app/video.py
import os
import json
import httpx
import subprocess
import tempfile

import redis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from security import verify_jwt
from minio_client import (
    upload_video,
    upload_thumbnail,
    get_video_stream,
    get_thumbnail_stream,
    list_user_videos,
)

from ai import (
    insert_final_video,
    mark_youtube_uploaded,
    insert_operation_log,
)

router = APIRouter(tags=["video"])

# ==============================
# KIE
# ==============================
KIE_API_URL = "https://api.kie.ai/api/v1/veo/generate"
KIE_API_KEY = os.getenv("KIE_API_KEY")
if not KIE_API_KEY:
    raise RuntimeError("KIE_API_KEY is not set")

# ==============================
# Redis2 (AI Worker 전용)
# ==============================
REDIS2_HOST = os.getenv("AI_REDIS_HOST", "10.1.1.10")
REDIS2_PORT = int(os.getenv("AI_REDIS_PORT", "6379"))
REDIS2_QUEUE = os.getenv("AI_REDIS_QUEUE", "video_processing_jobs")

redis2 = redis.Redis(
    host=REDIS2_HOST,
    port=REDIS2_PORT,
    decode_responses=True,
)

# ==============================
# 상태 캐시 (UI 조회용)
# ==============================
TASKS = {}


class VideoGenerateRequest(BaseModel):
    prompt: str


# ======================================================
# 1️⃣ 영상 생성 요청
# ======================================================
@router.post("/generate")
async def generate_video(body: VideoGenerateRequest, user=Depends(verify_jwt)):
    user_id = user["sub"]

    payload = {
        "prompt": body.prompt,
        "model": "veo3_fast",
        "aspect_ratio": "9:16",
        "callBackUrl": "https://auth.justic.store/api/video/callback",
    }

    headers = {
        "Authorization": f"Bearer {KIE_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(KIE_API_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()

    task_id = data.get("data", {}).get("taskId")
    if not task_id:
        raise HTTPException(status_code=502, detail="No taskId")

    TASKS[task_id] = {
        "status": "QUEUED",
        "user_id": user_id,
    }

    return {"task_id": task_id, "status": "QUEUED"}


# ======================================================
# 2️⃣ KIE 콜백 → 원본 업로드 → Redis2 PUSH (job 2개)
# ======================================================
@router.post("/callback")
async def video_callback(payload: dict):
    data = payload.get("data", {})
    task_id = data.get("taskId")
    urls = data.get("info", {}).get("resultUrls", [])

    task = TASKS.get(task_id)
    if not task or not urls:
        return {"code": 200}

    user_id = task["user_id"]
    tmp_video = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.get(urls[0])
            r.raise_for_status()
            with open(tmp_video, "wb") as f:
                f.write(r.content)

        # 원본 업로드
        upload_video(user_id, task_id, tmp_video)

        # ✅ job 2개 푸시 (v1 / v2)
        input_key = f"{user_id}/{task_id}.mp4"
        jobs = [
            {
                "output_key": f"{user_id}/{task_id}_processed.mp4",
                "variant": "v1",
            },
            {
                "output_key": f"{user_id}/{task_id}_processed_v2.mp4",
                "variant": "v2",
            },
        ]

        for j in jobs:
            redis2.lpush(
                REDIS2_QUEUE,
                json.dumps({
                    "task_id": task_id,
                    "user_id": user_id,
                    "input_key": input_key,
                    "output_key": j["output_key"],
                    "variant": j["variant"],  # 👈 ai_worker가 CAPTION_VARIANT로 넘기면 generate_caption.py가 분기됨
                })
            )

        task["status"] = "QUEUED_FOR_AI"

    except Exception as e:
        task["status"] = "FAILED"
        print("[callback error]", e)

    finally:
        os.remove(tmp_video)

    return {"code": 200}


# ======================================================
# 3️⃣ 영상 목록
# ======================================================
@router.get("/list")
def list_videos(user=Depends(verify_jwt)):
    user_id = user["sub"]
    names = list_user_videos(user_id)

    videos = {}
    for name in names:
        # name이 확장자 포함/미포함일 수 있어 둘 다 대응
        clean = name
        if clean.endswith(".mp4"):
            clean = clean[:-4]

        # base task id 추출 (processed/v2 제거)
        base = clean.replace("_processed_v2", "").replace("_processed", "")

        videos.setdefault(base, {
            "task_id": base,
            "has_original": False,
            "has_processed": False,      # v1
            "has_processed_v2": False,   # v2
        })

        if clean.endswith("_processed_v2"):
            videos[base]["has_processed_v2"] = True
        elif clean.endswith("_processed"):
            videos[base]["has_processed"] = True
        else:
            videos[base]["has_original"] = True

    return {"videos": list(videos.values())}


# ======================================================
# 4️⃣ 상태 조회 (v1/v2 둘 다 체크)
# ======================================================
@router.get("/status/{task_id}")
def get_status(task_id: str, user=Depends(verify_jwt)):
    user_id = user["sub"]

    try:
        names = list_user_videos(user_id)

        # 확장자 유무 케이스 모두 대응
        def exists(n: str) -> bool:
            return (n in names) or (f"{n}.mp4" in names)

        has_v1 = exists(f"{task_id}_processed")
        has_v2 = exists(f"{task_id}_processed_v2")

        if has_v1 and has_v2:
            return {"task_id": task_id, "status": "DONE"}

        if has_v1 or has_v2:
            # v1만 끝났거나 v2만 끝난 경우
            return {
                "task_id": task_id,
                "status": "PARTIAL",
                "done": {"v1": has_v1, "v2": has_v2},
            }

        # 원본만 있는 경우(선택)
        if exists(task_id):
            pass

    except Exception as e:
        print("[status check error]", e)

    task = TASKS.get(task_id)
    if not task:
        return {"task_id": task_id, "status": "PENDING"}

    if task.get("status") == "FAILED":
        return {"task_id": task_id, "status": "FAILED"}

    return {"task_id": task_id, "status": task["status"]}


# ======================================================
# 5️⃣ 영상 스트리밍 (v2 추가)
# ======================================================
@router.get("/stream/{task_id}")
def stream_video(
    task_id: str,
    type: str = Query("original", enum=["original", "processed", "processed_v2"]),
    user=Depends(verify_jwt),
):
    user_id = user["sub"]

    if type == "original":
        obj = get_video_stream(user_id, task_id, processed=False)
    elif type == "processed":
        obj = get_video_stream(user_id, task_id, processed=True)  # 기존 유지 (_processed)
    else:
        # ✅ processed_v2는 minio_client가 모르면, task_id에 suffix 붙이고 processed=False로 우회
        obj = get_video_stream(user_id, f"{task_id}_processed_v2", processed=False)

    def gen():
        for c in obj.stream(1024 * 1024):
            yield c
        obj.close()
        obj.release_conn()

    return StreamingResponse(gen(), media_type="video/mp4")


# ======================================================
# 6️⃣ 썸네일
# ======================================================
@router.get("/thumb/{task_id}.jpg")
def get_thumbnail(task_id: str, user=Depends(verify_jwt)):
    user_id = user["sub"]

    try:
        obj = get_thumbnail_stream(user_id, task_id)
    except Exception:
        tmp_video = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
        tmp_thumb = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg").name

        vobj = get_video_stream(user_id, task_id)
        with open(tmp_video, "wb") as f:
            for c in vobj.stream(1024 * 1024):
                f.write(c)

        subprocess.run(
            ["ffmpeg", "-y", "-ss", "00:00:01", "-i", tmp_video, "-frames:v", "1", tmp_thumb],
            check=True,
        )

        upload_thumbnail(user_id, task_id, tmp_thumb)
        obj = get_thumbnail_stream(user_id, task_id)

        os.remove(tmp_video)
        os.remove(tmp_thumb)

    def gen():
        for c in obj.stream(256 * 1024):
            yield c
        obj.close()
        obj.release_conn()

    return StreamingResponse(gen(), media_type="image/jpeg")


# ======================================================
# upload model
# ======================================================
class YouTubeUploadRequest(BaseModel):
    task_id: str
    type: str
    title: str


# ======================================================
# YouTube Upload API (FIXED)
# ======================================================
@router.post("/upload/youtube")
async def upload_youtube(
    body: YouTubeUploadRequest,
    user=Depends(verify_jwt),
):
    user_id = user["sub"]
    task_id = body.task_id
    video_type = body.type

    # ✅ v2 타입도 받게 확장 (기존 기능 유지 + v2 추가)
    if video_type not in ("original", "processed", "processed_v2"):
        raise HTTPException(400, "Invalid video type")

    video_key = f"{user_id}/{task_id}"
    if video_type == "processed":
        video_key += "_processed"
    elif video_type == "processed_v2":
        video_key += "_processed_v2"
    video_key += ".mp4"

    # ✅ DB 먼저 INSERT
    await insert_final_video(
        video_key=video_key,
        user_id=user_id,
        title=body.title,
        description=f"Generated by Justic AI\nTask ID: {task_id}",
    )

    tmp_video = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name

    try:
        if video_type == "original":
            obj = get_video_stream(user_id=user_id, task_id=task_id, processed=False)
        elif video_type == "processed":
            obj = get_video_stream(user_id=user_id, task_id=task_id, processed=True)
        else:
            obj = get_video_stream(user_id=user_id, task_id=f"{task_id}_processed_v2", processed=False)

        with open(tmp_video, "wb") as f:
            for c in obj.stream(1024 * 1024):
                f.write(c)

        obj.close()
        obj.release_conn()

        from googleapiclient.http import MediaFileUpload
        from google_auth import get_youtube_service

        youtube = get_youtube_service(user_id)

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": body.title,
                    "description": f"Generated by Justic AI\nTask ID: {task_id}",
                    "categoryId": "22",
                },
                "status": {"privacyStatus": "private"},
            },
            media_body=MediaFileUpload(tmp_video, mimetype="video/mp4", resumable=True),
        )

        response = request.execute()
        youtube_id = response.get("id") if response else None

        if youtube_id:
            await mark_youtube_uploaded(
                video_key=video_key,
                youtube_video_id=youtube_id,
            )

        await insert_operation_log(
            user_id=user_id,
            log_type="YOUTUBE_UPLOAD",
            status="SUCCESS" if youtube_id else "UNKNOWN",
            video_key=video_key,
            message=f"YouTube upload finished (youtube_id={youtube_id})",
        )

        return {"status": "UPLOADED", "youtube_video_id": youtube_id}

    except Exception as e:
        await insert_operation_log(
            user_id=user_id,
            log_type="YOUTUBE_UPLOAD",
            status="FAIL",
            video_key=video_key,
            message=f"YouTube upload failed: {repr(e)}",
        )
        raise HTTPException(500, "YouTube upload failed")

    finally:
        if os.path.exists(tmp_video):
            os.remove(tmp_video)
