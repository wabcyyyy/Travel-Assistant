USE travel_assistant;

-- 为已有数据库保存每日手册元数据，避免主题/备选方案等契约字段在异步落库时丢失。
ALTER TABLE itinerary_day
    ADD COLUMN metadata_json LONGTEXT DEFAULT NULL COMMENT '每日手册元数据 JSON（主题/路线/备选/拍照点/提醒）' AFTER note;
