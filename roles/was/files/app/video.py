# app/video.py
import os
import httpx
import subprocess
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from security import verify_jwt

router = APIRouter(tags=["video"])

# =============================
# External API
# =============================
KIE_API_URL = "https://api.kie.ai/api/v1/veo/generate"
KIE_API_KEY = os.getenv("KIE_API_KEY")

if not KIE_API_KEY:
    raise RuntimeError("KIE_API_KEY is not set")

# =============================
# Storage Path
# =============================
BASE_DIR = "/var/lib/veo"
VIDEO_BASE = f"{BASE_DIR}/videos"
THUMB_BASE = f"{BASE_DIR}/thumbs"

# =============================
# In-memory task store
# =============================
TASKS = {}

# =============================
# Request Schema
# =============================
class VideoGenerateRequest(BaseModel):
    prompt: str


# ======================================================
# 1. 영상 생성 요청 (JWT 필요)
# ======================================================
@router.post("/generate")
async def generate_video(
    body: VideoGenerateRequest,
    user=Depends(verify_jwt),
):
    user_id = user["sub"]

    payload = {
        "prompt": body.prompt,
        "model": "veo3_fast",
        "callBackUrl": "http://auth.justic.store:8000/api/video/callback",
    }

    headers = {
        "Authorization": f"Bearer {KIE_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(KIE_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()

    task_id = result.get("data", {}).get("taskId")
    if not task_id:
        raise HTTPException(status_code=502, detail="Invalid response")

    TASKS[task_id] = {
        "status": "QUEUED",
        "user_id": user_id,
    }

    return {"task_id": task_id, "status": "QUEUED"}


# ======================================================
# 2. 외부 API 콜백 (인증 ❌)
# ======================================================
@router.post("/callback")
async def video_callback(payload: dict):
    code = payload.get("code")
    data = payload.get("data", {})
    task_id = data.get("taskId")

    task = TASKS.get(task_id)
    if not task:
        return {"code": 200}

    if code != 200:
        task["status"] = "FAILED"
        return {"code": 200}

    urls = data.get("info", {}).get("resultUrls", [])
    if not urls:
        task["status"] = "FAILED"
        return {"code": 200}

    user_id = task["user_id"]

    user_video_dir = f"{VIDEO_BASE}/{user_id}"
    os.makedirs(user_video_dir, exist_ok=True)

    video_path = f"{user_video_dir}/{task_id}.mp4"

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(urls[0])
        r.raise_for_status()
        with open(video_path, "wb") as f:
            f.write(r.content)

    task["status"] = "DONE"

    return {"code": 200}


# ======================================================
# 3. 내 영상 목록 조회 (JWT 필요)
# ======================================================
@router.get("/list")
def list_videos(user=Depends(verify_jwt)):
    user_id = user["sub"]
    user_video_dir = f"{VIDEO_BASE}/{user_id}"

    if not os.path.exists(user_video_dir):
        return {"videos": []}

    files = [
        f.replace(".mp4", "")
        for f in os.listdir(user_video_dir)
        if f.endswith(".mp4")
    ]

    return {"videos": [{"task_id": f} for f in sorted(files, reverse=True)]}


# ======================================================
# 4. 상태 조회 (JWT 필요)
# ======================================================
@router.get("/status/{task_id}")
def get_status(task_id: str, user=Depends(verify_jwt)):
    task = TASKS.get(task_id)
    if not task or task["user_id"] != user["sub"]:
        raise HTTPException(status_code=404)

    return {"task_id": task_id, "status": task["status"]}


# ======================================================
# 5. 영상 스트리밍 (JWT 필요)
# ======================================================
@router.get("/stream/{task_id}")
def stream_video(task_id: str, user=Depends(verify_jwt)):
    user_id = user["sub"]
    path = f"{VIDEO_BASE}/{user_id}/{task_id}.mp4"

    if not os.path.exists(path):
        raise HTTPException(status_code=404)

    return FileResponse(path, media_type="video/mp4")


# ======================================================
# 6. 썸네일 이미지 제공 (인증 ❌ 공개)
# ======================================================
@router.get("/thumb/{task_id}.jpg")
def get_thumbnail(task_id: str):
    # task_id → 어떤 유저인지 찾기
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404)

    user_id = task["user_id"]

    video_path = f"{VIDEO_BASE}/{user_id}/{task_id}.mp4"
    thumb_dir = f"{THUMB_BASE}/{user_id}"
    thumb_path = f"{thumb_dir}/{task_id}.jpg"

    if not os.path.exists(video_path):
        raise HTTPException(status_code=404)

    os.makedirs(thumb_dir, exist_ok=True)

    if not os.path.exists(thumb_path):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss", "00:00:01",
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "2",
                thumb_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return FileResponse(thumb_path, media_type="image/jpeg")
