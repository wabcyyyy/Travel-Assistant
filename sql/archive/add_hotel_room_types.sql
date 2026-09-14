-- 酒店房型参考价。价格为知识库基准价，最终展示仍会按入住日期叠加季节系数。
CREATE TABLE IF NOT EXISTS hotel_room_type (
    id          BIGINT         NOT NULL AUTO_INCREMENT,
    poi_id      BIGINT         NOT NULL COMMENT '关联 poi_knowledge 酒店',
    room_name   VARCHAR(128)   NOT NULL COMMENT '房型名称',
    base_price  DECIMAL(10, 2) NOT NULL COMMENT '每晚单间参考基准价',
    capacity    INT            NOT NULL DEFAULT 2 COMMENT '建议入住人数',
    bed_type    VARCHAR(64)    DEFAULT NULL,
    breakfast   VARCHAR(64)    DEFAULT NULL,
    description VARCHAR(512)   DEFAULT NULL,
    is_default  TINYINT        NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uk_hotel_room (poi_id, room_name),
    KEY idx_hotel (poi_id)
) ENGINE = InnoDB COMMENT '酒店房型与参考价格';

INSERT INTO hotel_room_type
    (poi_id, room_name, base_price, capacity, bed_type, breakfast, description, is_default)
SELECT p.id, r.room_name, r.base_price, r.capacity, r.bed_type, r.breakfast, r.description, r.is_default
FROM poi_knowledge p
JOIN (
    SELECT '杭州法云安缦' hotel_name, '村庄客舍' room_name, 5200.00 base_price, 2 capacity,
           '大床/双床' bed_type, '视价格方案而定' breakfast, '基础房型，保留法云村落风格与私密庭院体验。' description, 1 is_default
    UNION ALL SELECT '杭州法云安缦', '村庄套房', 6800.00, 2, '大床', '视价格方案而定', '面积与起居空间更大，适合希望提升居住体验的客人。', 0
    UNION ALL SELECT '杭州法云安缦', '法云安缦院落', 12000.00, 4, '多卧室', '视价格方案而定', '独立院落型房型，空间和私密性显著提升。', 0
    UNION ALL SELECT '杭州西子湖四季酒店', '豪华园景客房', 3200.00, 2, '大床/双床', '视价格方案而定', '园林景观基础房型。', 1
    UNION ALL SELECT '杭州西子湖四季酒店', '西湖景观客房', 4200.00, 2, '大床/双床', '视价格方案而定', '侧重西湖景观与度假体验。', 0
    UNION ALL SELECT '杭州西子湖四季酒店', '湖畔套房', 7800.00, 2, '大床', '视价格方案而定', '独立起居空间，适合高规格度假需求。', 0
    UNION ALL SELECT '杭州西子宾馆汪庄', '豪华园景房', 1250.00, 2, '大床/双床', '视价格方案而定', '园林景观基础房型。', 1
    UNION ALL SELECT '杭州西子宾馆汪庄', '西湖景观房', 1800.00, 2, '大床/双床', '视价格方案而定', '面向西湖景观的升级房型。', 0
    UNION ALL SELECT '杭州西子宾馆汪庄', '汪庄套房', 3500.00, 2, '大床', '视价格方案而定', '拥有独立起居空间的高端套房。', 0
    UNION ALL SELECT '杭州湖滨银泰in77亚朵酒店', '高级客房', 480.00, 2, '大床/双床', '视价格方案而定', '基础舒适房型。', 1
    UNION ALL SELECT '杭州湖滨银泰in77亚朵酒店', '几木湖景房', 680.00, 2, '大床', '视价格方案而定', '面积和景观有所提升。', 0
    UNION ALL SELECT '杭州柏悦酒店', '柏悦客房', 2200.00, 2, '大床/双床', '视价格方案而定', '高空城市景观基础房型。', 1
    UNION ALL SELECT '杭州柏悦酒店', '江景客房', 2800.00, 2, '大床', '视价格方案而定', '面向钱塘江的景观升级房型。', 0
    UNION ALL SELECT '杭州柏悦酒店', '柏悦套房', 5200.00, 2, '大床', '视价格方案而定', '带独立起居空间的高规格套房。', 0
    UNION ALL SELECT '杭州紫萱度假村', '园景客房', 3800.00, 2, '大床', '视价格方案而定', '强调园林氛围与私密体验的基础房型。', 1
    UNION ALL SELECT '杭州紫萱度假村', '独立庭院套房', 6800.00, 2, '大床', '视价格方案而定', '拥有独立庭院与更完整的度假空间。', 0
) r ON r.hotel_name = p.name
WHERE p.city = '杭州' AND p.category = 'hotel'
ON DUPLICATE KEY UPDATE
    base_price = VALUES(base_price), capacity = VALUES(capacity), bed_type = VALUES(bed_type),
    breakfast = VALUES(breakfast), description = VALUES(description), is_default = VALUES(is_default);
