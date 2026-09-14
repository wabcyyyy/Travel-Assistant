USE travel_assistant;

ALTER TABLE user_preference
    ADD COLUMN source VARCHAR(24) NOT NULL DEFAULT 'explicit' COMMENT '来源 explicit/inferred/feedback' AFTER count,
    ADD COLUMN confidence DECIMAL(5,4) NOT NULL DEFAULT 1.0000 COMMENT '偏好置信度' AFTER source,
    ADD COLUMN negative TINYINT NOT NULL DEFAULT 0 COMMENT '是否为负反馈' AFTER confidence,
    ADD COLUMN hard_constraint TINYINT NOT NULL DEFAULT 0 COMMENT '是否为硬约束' AFTER negative,
    ADD COLUMN last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '最近出现时间' AFTER hard_constraint;
