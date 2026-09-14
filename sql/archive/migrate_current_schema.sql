-- 将已有 travel_assistant 库升级到当前后端实体结构。
-- 仅用于旧库；全新环境请直接执行 schema.sql。
USE travel_assistant;

CREATE TABLE IF NOT EXISTS user_preference (
  id BIGINT NOT NULL AUTO_INCREMENT, user_id BIGINT NOT NULL,
  pref_label VARCHAR(32) NOT NULL, count INT NOT NULL DEFAULT 1,
  source VARCHAR(24) NOT NULL DEFAULT 'explicit', confidence DECIMAL(5,4) NOT NULL DEFAULT 1.0000,
  negative TINYINT NOT NULL DEFAULT 0, hard_constraint TINYINT NOT NULL DEFAULT 0,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id), UNIQUE KEY uk_user_pref (user_id, pref_label), KEY idx_user (user_id)
) ENGINE=InnoDB;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='itinerary_main' AND column_name='stay_nights')=0,
  'ALTER TABLE itinerary_main ADD COLUMN stay_nights INT NOT NULL DEFAULT 0 AFTER hotel_tier', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='itinerary_day' AND column_name='metadata_json')=0,
  'ALTER TABLE itinerary_day ADD COLUMN metadata_json LONGTEXT DEFAULT NULL AFTER note', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='itinerary_day' AND column_name='generation_action_id')=0,
  'ALTER TABLE itinerary_day ADD COLUMN generation_action_id VARCHAR(96) DEFAULT NULL, ADD COLUMN generation_fingerprint CHAR(64) DEFAULT NULL, ADD COLUMN generation_status VARCHAR(24) NOT NULL DEFAULT ''PENDING'', ADD COLUMN generation_error VARCHAR(512) DEFAULT NULL', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='itinerary_item' AND column_name='image_url')=0,
  'ALTER TABLE itinerary_item ADD COLUMN open_time VARCHAR(64) DEFAULT NULL, ADD COLUMN image_url VARCHAR(1024) DEFAULT NULL, ADD COLUMN source VARCHAR(128) DEFAULT NULL, ADD COLUMN source_updated_at DATETIME DEFAULT NULL, ADD COLUMN verification_status VARCHAR(24) NOT NULL DEFAULT ''unverified'', ADD COLUMN value_kind VARCHAR(16) NOT NULL DEFAULT ''generated'', ADD COLUMN freshness_status VARCHAR(16) NOT NULL DEFAULT ''unknown'', ADD COLUMN review_requirement VARCHAR(24) NOT NULL DEFAULT ''before_departure'', ADD COLUMN fact_evidence_json LONGTEXT DEFAULT NULL', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='poi_knowledge' AND column_name='source')=0,
  'ALTER TABLE poi_knowledge ADD COLUMN source VARCHAR(128) NOT NULL DEFAULT ''mysql.poi_knowledge'', ADD COLUMN source_updated_at DATETIME DEFAULT NULL', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='user_preference' AND column_name='source')=0,
  'ALTER TABLE user_preference ADD COLUMN source VARCHAR(24) NOT NULL DEFAULT ''explicit'', ADD COLUMN confidence DECIMAL(5,4) NOT NULL DEFAULT 1.0000, ADD COLUMN negative TINYINT NOT NULL DEFAULT 0, ADD COLUMN hard_constraint TINYINT NOT NULL DEFAULT 0, ADD COLUMN last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

CREATE TABLE IF NOT EXISTS itinerary_version (
  id BIGINT NOT NULL AUTO_INCREMENT, itinerary_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
  parent_version_id BIGINT DEFAULT NULL, version_no INT NOT NULL,
  operation VARCHAR(24) NOT NULL DEFAULT 'snapshot', summary VARCHAR(255) DEFAULT NULL,
  snapshot_json LONGTEXT NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id), UNIQUE KEY uk_itinerary_version (itinerary_id, version_no),
  KEY idx_version_itinerary (itinerary_id, id)
) ENGINE=InnoDB;
