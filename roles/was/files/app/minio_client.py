# app/minio_client.py
import os
from minio import Minio

MINIO_BUCKET = os.getenv("MINIO_BUCKET", "videos")

minio_client = Minio(
    os.getenv("MINIO_ENDPOINT"),
    access_key=os.getenv("MINIO_ACCESS_KEY"),
    secret_key=os.getenv("MINIO_SECRET_KEY"),
    secure=False
)


def ensure_bucket():
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)


# ======================
# 업로드
# ======================

def upload_video(user_id: str, task_id: str, file_path: str, processed: bool = False):
    ensure_bucket()  # ✅ 추가 (중요)

    filename = f"{task_id}_processed.mp4" if processed else f"{task_id}.mp4"

    minio_client.fput_object(
        MINIO_BUCKET,
        f"{user_id}/{filename}",
        file_path,
        content_type="video/mp4"
    )


def upload_thumbnail(user_id: str, task_id: str, thumb_path: str):
    ensure_bucket()  # ✅ 추가 (중요)

    minio_client.fput_object(
        MINIO_BUCKET,
        f"{user_id}/{task_id}.jpg",
        thumb_path,
        content_type="image/jpeg"
    )


# ======================
# 스트리밍
# ======================

def get_video_stream(user_id: str, task_id: str, processed: bool = False):
    filename = f"{task_id}_processed.mp4" if processed else f"{task_id}.mp4"

    return minio_client.get_object(
        MINIO_BUCKET,
        f"{user_id}/{filename}"
    )


def get_thumbnail_stream(user_id: str, task_id: str):
    return minio_client.get_object(
        MINIO_BUCKET,
        f"{user_id}/{task_id}.jpg"
    )


# ======================
# 리스트
# ======================

def list_user_videos(user_id: str):
    """
    반환 예:
    [
      "taskid",
      "taskid_processed"
    ]
    """
    objects = minio_client.list_objects(
        MINIO_BUCKET,
        prefix=f"{user_id}/",
        recursive=True,
    )

    results = []
    for obj in objects:
        name = obj.object_name.split("/")[-1]

        if name.endswith(".mp4"):
            results.append(name.replace(".mp4", ""))

    return sorted(results, reverse=True)
