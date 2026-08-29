USE travel_assistant;

-- 为已有数据库补充 POI 来源元数据。执行一次即可。
ALTER TABLE poi_knowledge
    ADD COLUMN source VARCHAR(128) NOT NULL DEFAULT 'mysql.poi_knowledge' COMMENT '权威数据来源' AFTER description,
    ADD COLUMN source_updated_at DATETIME DEFAULT NULL COMMENT '来源数据更新时间' AFTER source;
