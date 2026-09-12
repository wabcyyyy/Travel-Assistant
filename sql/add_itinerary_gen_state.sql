-- 显式生成状态机字段（AD6/M2-②，J3）。
-- 背景：此前生成状态只靠 itinerary_main.status(1/2/3) + plan_note 内嵌 "[已自动续跑一次]"
-- 文案 + updated_at 5 分钟启发式承载，竞态多、难测试。gen_state 与 status 并行：
-- status 面向用户可见语义不变，gen_state 面向恢复任务/运维精确判定。
-- 已执行过 schema.sql 的环境可单独执行本迁移。
ALTER TABLE itinerary_main
    ADD COLUMN gen_state       VARCHAR(16) DEFAULT NULL COMMENT '生成状态机：GENERATING/PARTIAL/COMPLETED/FAILED，NULL=迁移前存量' AFTER suggestions_json,
    ADD COLUMN gen_started_at  DATETIME    DEFAULT NULL COMMENT '本次生成开始时间（含恢复续跑刷新）' AFTER gen_state,
    ADD COLUMN gen_finished_at DATETIME    DEFAULT NULL COMMENT '本次生成结束时间' AFTER gen_started_at,
    ADD COLUMN gen_resumed     TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '已自动续跑过一次（防失败-重生成死循环）' AFTER gen_finished_at;

-- 回填依据：
-- 1) gen_state 按 status 历史语义映射——1=生成中(GENERATING)、2=已生成(COMPLETED)、3=失败(FAILED)；
--    三者互斥，各条件加 gen_state IS NULL 守卫保证幂等重跑安全。
-- 2) plan_note 含 "[已自动续跑一次]" 是旧续跑标记实现，语义等价于 gen_resumed=1，
--    回填后恢复任务即可依据 gen_resumed 阻止二次续跑（与旧防死循环行为一致）。
UPDATE itinerary_main SET gen_state = 'COMPLETED'  WHERE status = 2 AND gen_state IS NULL;
UPDATE itinerary_main SET gen_state = 'FAILED'     WHERE status = 3 AND gen_state IS NULL;
UPDATE itinerary_main SET gen_state = 'GENERATING' WHERE status = 1 AND gen_state IS NULL;
UPDATE itinerary_main SET gen_resumed = 1 WHERE plan_note LIKE '%[已自动续跑一次]%';
