CREATE TABLE IF NOT EXISTS itinerary_chat_message (
    id                 BIGINT       NOT NULL AUTO_INCREMENT,
    itinerary_id       BIGINT       NOT NULL,
    user_id            BIGINT       NOT NULL,
    role               VARCHAR(16)  NOT NULL COMMENT 'user/ai',
    content            TEXT         NOT NULL,
    plans_json         LONGTEXT     DEFAULT NULL,
    hotel_options_json LONGTEXT     DEFAULT NULL,
    changed            TINYINT      NOT NULL DEFAULT 0,
    created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_itinerary_user (itinerary_id, user_id, id)
) ENGINE = InnoDB COMMENT '行程对话记忆';
