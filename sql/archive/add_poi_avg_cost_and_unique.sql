-- 2026-09-10 审计修复 #14/#15：
-- 1) poi_knowledge 增加 avg_cost 列：高德 biz_ext.cost 是"人均消费"，
--    此前被一律写进 ticket_price（门票参考价），景点票价系统性偏差。
-- 2) 收敛历史重复行并加 (city, name) 唯一键，upsert 获得数据库级幂等兜底。

ALTER TABLE poi_knowledge
    ADD COLUMN avg_cost DECIMAL(10, 2) DEFAULT NULL
        COMMENT '人均消费(元)：餐饮人均/景点园内平均花费，非门票价' AFTER ticket_price;

-- 景点行的 ticket_price 历史上多数来自高德 cost（人均），如实迁移：
-- 凡 source 含 amap 的景点行，其 ticket_price 就是被误存的人均消费，搬到
-- avg_cost 并把 ticket_price 置 NULL（门票未知）。
-- 例外：source 不含 amap 的纯 Wikivoyage/LLM 行，其 ticket_price 本来就是
-- 模型/条目给出的门票参考价，保留不动。
-- （amap+wikivoyage 合并行中，门票价仅在 amap cost 为空时才会被 wv 填充，
--   无法事后精确区分；这类行含 amap，按人均迁移，宁可门票未知也不冒充门票价。）
UPDATE poi_knowledge
SET avg_cost = ticket_price, ticket_price = NULL
WHERE category = 'attraction'
  AND ticket_price IS NOT NULL
  AND source LIKE '%amap%';

-- 先清洗名称尾部标点（如"宏豪浦江一号(陆家嘴店)."）。管线 norm_name 会剥掉
-- 这些标点做匹配，若不清洗，唯一键 (city,name,category) 挡不住"标点差异"
-- 的重复行。MySQL TRIM(TRAILING) 去除的是整串而非字符集，需逐字符嵌套。
-- 清洗可能制造新重复，故收敛 DELETE 放在清洗之后。
UPDATE poi_knowledge
SET name = TRIM(TRAILING '；' FROM TRIM(TRAILING ';' FROM TRIM(TRAILING '，' FROM
    TRIM(TRAILING ',' FROM TRIM(TRAILING '、' FROM TRIM(TRAILING '。' FROM
    TRIM(TRAILING '.' FROM TRIM(TRAILING ' ' FROM name))))))))
WHERE name REGEXP '[ .。,，;；]$';

-- 收敛 (city, name, category) 重复行：保留信息最完整的一行（非空字段数最多，
-- 其次 id 最大），其余删除。注意唯一键必须含 category——"和平饭店"这类
-- 酒店内餐厅是同名不同品类的合法双记录，按 (city,name) 收敛会误删。
-- 执行前请先备份 poi_knowledge。
DELETE p FROM poi_knowledge p
JOIN (
    SELECT city, name, category,
           SUBSTRING_INDEX(
               GROUP_CONCAT(id ORDER BY
                   (COALESCE(address IS NOT NULL) + COALESCE(latitude IS NOT NULL)
                    + COALESCE(ticket_price IS NOT NULL) + COALESCE(avg_cost IS NOT NULL)
                    + COALESCE(open_time IS NOT NULL) + COALESCE(description IS NOT NULL)
                    + COALESCE(rating IS NOT NULL)) DESC, id DESC),
               ',', 1) AS keep_id
    FROM poi_knowledge
    GROUP BY city, name, category
    HAVING COUNT(*) > 1
) d ON p.city = d.city AND p.name = d.name AND p.category = d.category AND p.id != d.keep_id;

ALTER TABLE poi_knowledge
    ADD UNIQUE KEY uk_city_name_category (city, name, category);
