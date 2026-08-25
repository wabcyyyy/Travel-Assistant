-- 管家讲解与景点详细介绍字段（幂等需手动判断，仅执行一次）
ALTER TABLE itinerary_main ADD COLUMN plan_note TEXT NULL COMMENT 'AI管家规划讲解';
ALTER TABLE itinerary_item ADD COLUMN intro VARCHAR(600) NULL COMMENT '景点详细介绍(LLM生成)';
