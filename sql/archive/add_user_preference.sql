USE travel_assistant;

-- 用户偏好统计表：记录每个用户选择各偏好标签的次数，用于下次生成时自动推荐
CREATE TABLE IF NOT EXISTS user_preference (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    user_id       BIGINT       NOT NULL,
    pref_label    VARCHAR(32)  NOT NULL COMMENT '偏好标签（如 人文历史/美食）',
    count         INT          NOT NULL DEFAULT 1 COMMENT '累计选择次数',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_pref (user_id, pref_label),
    KEY idx_user (user_id)
) ENGINE = InnoDB COMMENT '用户偏好统计';
