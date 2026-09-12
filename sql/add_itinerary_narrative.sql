-- 叙事字段迁移（M3-③，AD5/AD3 §4.4.4）。
-- 背景：Python 生成契约新增叙事字段——TripItem.whyThis（≤120 字叙事理由，attraction 必填）、
-- DailyPlan.tripTheme（≤40 字整趟主题标题，仅 day_no=1 的 generate-day 响应携带）。
-- Java 侧落为独立列（why_note / trip_theme），便于 VO/快照/PDF 直接读取；
-- 备选日方案 dayOptions 仍随 itinerary_day.metadata_json 承载，不占主表列。
-- 已执行过 schema.sql 的环境可单独执行本迁移；本脚本不包含 gen_state（上一轮迁移已加）。
-- 幂等说明：MySQL 的 ADD COLUMN 不支持 IF NOT EXISTS，重复执行会报
-- Duplicate column name 'why_note' / 'trip_theme'，属预期行为——
-- 可先查 information_schema.COLUMNS 确认列不存在再执行，或直接忽略该报错。
ALTER TABLE itinerary_item
    ADD COLUMN why_note VARCHAR(255) DEFAULT NULL COMMENT '叙事理由（why_this，value_kind=generated）' AFTER intro;

ALTER TABLE itinerary_main
    ADD COLUMN trip_theme VARCHAR(64) DEFAULT NULL COMMENT '整趟主题标题（来自生成契约 trip_theme）' AFTER suggestions_json;
