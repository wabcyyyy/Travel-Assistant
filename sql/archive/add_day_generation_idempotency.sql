-- 每日生成幂等与恢复字段。已执行过 schema.sql 的环境可单独执行本迁移。
ALTER TABLE itinerary_day
    ADD COLUMN generation_action_id VARCHAR(96) DEFAULT NULL COMMENT '稳定的每日生成动作 ID' AFTER note,
    ADD COLUMN generation_fingerprint CHAR(64) DEFAULT NULL COMMENT '生成参数 SHA-256 指纹' AFTER generation_action_id,
    ADD COLUMN generation_status VARCHAR(24) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/RUNNING/SUCCEEDED/FAILED/TIMED_OUT_UNKNOWN' AFTER generation_fingerprint,
    ADD COLUMN generation_error VARCHAR(512) DEFAULT NULL COMMENT '最近一次生成错误' AFTER generation_status,
    ADD UNIQUE KEY uk_itinerary_day_no (itinerary_id, day_no),
    ADD UNIQUE KEY uk_generation_action (generation_action_id),
    ADD KEY idx_generation_status (generation_status);

-- 迁移前已经写入项目的日期视为成功，避免首次恢复时无意义地重新生成。
UPDATE itinerary_day d
SET d.generation_status = 'SUCCEEDED'
WHERE d.generation_status = 'PENDING'
  AND EXISTS (
      SELECT 1 FROM itinerary_item i
      WHERE i.day_id = d.id AND i.deleted = 0
  );
