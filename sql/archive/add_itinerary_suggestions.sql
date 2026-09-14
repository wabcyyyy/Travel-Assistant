-- 行程级备选池：LLM 生成时从候选池挑出、未排入行程的优质点位（发现更多）。
-- 条目结构：{poiId, name, category(attraction|activity|food|hotel|souvenir),
--            address, latitude, longitude, intro, needReservation, estimatedCost, used}
ALTER TABLE itinerary_main
    ADD COLUMN suggestions_json TEXT DEFAULT NULL
        COMMENT '备选池（发现更多）JSON，来自生成时候选池中未排入行程的优质点位'
        AFTER plan_note;
