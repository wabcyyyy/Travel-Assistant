USE travel_assistant;

-- 为已有数据库补充住宿档次偏好；重复执行安全。
SET @hotel_tier_exists = (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'itinerary_main'
      AND column_name = 'hotel_tier'
);
SET @hotel_tier_sql = IF(
    @hotel_tier_exists = 0,
    'ALTER TABLE itinerary_main ADD COLUMN hotel_tier VARCHAR(16) DEFAULT NULL COMMENT ''住宿档次偏好'' AFTER preferences',
    'SELECT 1'
);
PREPARE hotel_tier_stmt FROM @hotel_tier_sql;
EXECUTE hotel_tier_stmt;
DEALLOCATE PREPARE hotel_tier_stmt;
