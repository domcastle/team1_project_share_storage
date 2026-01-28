-- =========================
-- Final Selected Videos
-- =========================
CREATE TABLE IF NOT EXISTS ai_final_videos (
  final_video_id BIGSERIAL PRIMARY KEY,

  -- 내부 식별자 (MinIO / AI 서버 기준 ID)
  video_key VARCHAR(255) NOT NULL UNIQUE,

  -- 소유 사용자 (oauth_users.user_id)
  user_id VARCHAR(255) NOT NULL,

  -- YouTube 업로드 정보
  youtube_uploaded BOOLEAN DEFAULT FALSE,
  youtube_video_id VARCHAR(255),

  -- 선택 시점
  selected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  -- 업로드 시점
  youtube_uploaded_at TIMESTAMP,

  -- 확장용 메타
  title VARCHAR(255),
  description TEXT
);

-- 조회 최적화
CREATE INDEX IF NOT EXISTS idx_final_videos_user
  ON ai_final_videos(user_id);

CREATE INDEX IF NOT EXISTS idx_final_videos_youtube
  ON ai_final_videos(youtube_uploaded);

-- =========================
-- Operation / Policy Logs
-- =========================
CREATE TABLE IF NOT EXISTS ai_operation_logs (
  log_id BIGSERIAL PRIMARY KEY,

  user_id VARCHAR(255),

  -- PRECHECK / UPLOAD / SYSTEM
  log_type VARCHAR(50) NOT NULL,

  -- BLOCKED / FAILED / SUCCESS
  status VARCHAR(30) NOT NULL,

  -- 관련 영상 (있을 경우만)
  video_key VARCHAR(255),

  -- 사유 / 메시지
  message TEXT NOT NULL,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_op_logs_user
  ON ai_operation_logs(user_id);

CREATE INDEX IF NOT EXISTS idx_op_logs_type
  ON ai_operation_logs(log_type);

CREATE INDEX IF NOT EXISTS idx_op_logs_created
  ON ai_operation_logs(created_at);