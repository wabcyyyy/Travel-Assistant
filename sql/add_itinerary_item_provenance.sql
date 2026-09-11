USE travel_assistant;

-- 为已经存在的数据库补充行程项的来源、时效和图片字段。执行一次即可。
ALTER TABLE itinerary_item
    ADD COLUMN open_time VARCHAR(64) DEFAULT NULL COMMENT '来源营业时间文本' AFTER remark,
    ADD COLUMN image_url VARCHAR(1024) DEFAULT NULL COMMENT '地点图片 URL（可选）' AFTER open_time,
    ADD COLUMN source VARCHAR(128) DEFAULT NULL COMMENT '本次事实来源标识' AFTER image_url,
    ADD COLUMN source_updated_at DATETIME DEFAULT NULL COMMENT '来源数据更新时间' AFTER source,
    ADD COLUMN verification_status VARCHAR(24) NOT NULL DEFAULT 'unverified' COMMENT 'verified/partially_verified/unverified' AFTER source_updated_at,
    ADD COLUMN value_kind VARCHAR(16) NOT NULL DEFAULT 'generated' COMMENT 'observed/estimated/generated' AFTER verification_status,
    ADD COLUMN freshness_status VARCHAR(16) NOT NULL DEFAULT 'unknown' COMMENT 'fresh/stale/unknown' AFTER value_kind,
    ADD COLUMN review_requirement VARCHAR(24) NOT NULL DEFAULT 'before_departure' COMMENT 'none/before_departure' AFTER freshness_status,
    ADD COLUMN fact_evidence_json LONGTEXT DEFAULT NULL COMMENT '字段级事实证据 JSON' AFTER review_requirement;
