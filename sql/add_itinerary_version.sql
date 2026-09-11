USE travel_assistant;

CREATE TABLE IF NOT EXISTS itinerary_version (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    itinerary_id    BIGINT       NOT NULL,
    user_id         BIGINT       NOT NULL,
    parent_version_id BIGINT     DEFAULT NULL,
    version_no      INT          NOT NULL,
    operation       VARCHAR(24)  NOT NULL DEFAULT 'snapshot',
    summary         VARCHAR(255) DEFAULT NULL,
    snapshot_json   LONGTEXT     NOT NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_itinerary_version (itinerary_id, version_no),
    KEY idx_version_itinerary (itinerary_id, id)
) ENGINE = InnoDB COMMENT '行程版本快照';
