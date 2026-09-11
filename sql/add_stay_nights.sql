-- 让启动恢复能够重建与原任务一致的逐日请求参数。
ALTER TABLE itinerary_main
    ADD COLUMN stay_nights INT NOT NULL DEFAULT 0 COMMENT '住宿晚数' AFTER hotel_tier;

-- 旧版本默认按“天数 - 1 晚”生成住宿；新建行程仍由业务层写入用户实际选择。
UPDATE itinerary_main
SET stay_nights = GREATEST(days - 1, 0)
WHERE stay_nights = 0 AND days > 1;
