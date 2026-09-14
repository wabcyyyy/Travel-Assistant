-- 补充杭州各住宿档次候选，供“降一档 / 同档更换 / 升一档 / 最高档”语义筛选使用。
-- ticket_price 为每晚单间基准价；逐条判重，可幂等重复执行。
INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '如家精选酒店杭州西湖湖滨店', 'hotel', '上城区庆春路221号',
       30.2573, 120.1642, 320.00, NULL, '14:00后入住', '住宿,经济型', 4.6,
       '经济型连锁酒店，靠近湖滨商圈，适合希望降低住宿支出的游客。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='如家精选酒店杭州西湖湖滨店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '海友酒店杭州西湖湖滨店', 'hotel', '上城区浣纱路221号',
       30.2541, 120.1658, 260.00, NULL, '14:00后入住', '住宿,经济型', 4.4,
       '经济型酒店，靠近湖滨商圈，适合优先控制住宿支出的游客。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='海友酒店杭州西湖湖滨店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '7天酒店杭州西湖店', 'hotel', '上城区解放路236号',
       30.2508, 120.1702, 280.00, NULL, '14:00后入住', '住宿,经济型', 4.3,
       '经济型连锁酒店，交通便利，以基础住宿功能和价格优势为主。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='7天酒店杭州西湖店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '全季酒店杭州西湖店', 'hotel', '上城区延安路179号',
       30.2469, 120.1650, 520.00, NULL, '14:00后入住', '住宿,舒适型', 4.7,
       '舒适型中端酒店，位于西湖湖滨步行范围内，交通与餐饮便利。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='全季酒店杭州西湖店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '桔子酒店杭州西湖湖滨店', 'hotel', '上城区平海路38号',
       30.2562, 120.1680, 560.00, NULL, '14:00后入住', '住宿,舒适型', 4.7,
       '舒适型设计酒店，靠近湖滨步行区，兼顾位置、设计感和日常便利。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='桔子酒店杭州西湖湖滨店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州西湖希尔顿欢朋酒店', 'hotel', '上城区延安路178号',
       30.2484, 120.1659, 620.00, NULL, '14:00后入住', '住宿,舒适型', 4.7,
       '舒适型国际连锁酒店，客房和早餐配置稳定，适合看重便利与标准化服务的游客。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州西湖希尔顿欢朋酒店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州维景国际大酒店', 'hotel', '上城区平海路2号',
       30.2570, 120.1715, 760.00, NULL, '14:00后入住', '住宿,高档型', 4.7,
       '高档型酒店，靠近西湖与湖滨商圈，公共设施和客房配置较完整。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州维景国际大酒店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州温德姆至尊豪廷大酒店', 'hotel', '拱墅区凤起路555号',
       30.2636, 120.1590, 980.00, NULL, '14:00后入住', '住宿,高档型', 4.8,
       '高档型湖滨酒店，邻近西湖东岸，适合看重位置与综合服务的游客。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州温德姆至尊豪廷大酒店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州大华饭店', 'hotel', '上城区南山路171号',
       30.2472, 120.1572, 880.00, NULL, '14:00后入住', '住宿,高档型', 4.7,
       '高档型湖滨酒店，位置贴近西湖，适合重视湖景区位和传统服务的游客。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州大华饭店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州城中香格里拉', 'hotel', '拱墅区长寿路6号',
       30.2609, 120.1641, 1080.00, NULL, '14:00后入住', '住宿,高档型', 4.8,
       '高档型城市酒店，与嘉里中心相连，购物、餐饮和西湖出行都较便利。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州城中香格里拉' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州君悦酒店', 'hotel', '上城区湖滨路28号',
       30.2524, 120.1604, 1450.00, NULL, '14:00后入住', '住宿,豪华型', 4.8,
       '豪华型五星酒店，正对西湖湖滨，兼顾核心区位置、湖景与完整服务。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州君悦酒店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州康莱德酒店', 'hotel', '上城区新业路228号',
       30.2460, 120.2112, 1550.00, NULL, '14:00后入住', '住宿,豪华型', 4.8,
       '豪华型高层酒店，拥有城市景观、品质餐饮与完善的高端商务设施。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州康莱德酒店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州黄龙饭店', 'hotel', '西湖区曙光路120号',
       30.2721, 120.1416, 1200.00, NULL, '14:00后入住', '住宿,豪华型', 4.8,
       '豪华型五星酒店，靠近黄龙与西湖景区，综合设施和商务服务成熟。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州黄龙饭店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州索菲特西湖大酒店', 'hotel', '上城区西湖大道333号',
       30.2456, 120.1635, 1300.00, NULL, '14:00后入住', '住宿,豪华型', 4.7,
       '豪华型五星酒店，步行可达西湖，兼具法式风格、湖滨位置与完整服务。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州索菲特西湖大酒店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州西子湖四季酒店', 'hotel', '西湖区灵隐路5号',
       30.2483, 120.1370, 3200.00, NULL, '14:00后入住', '住宿,奢华型', 4.9,
       '奢华型园林度假酒店，毗邻西湖，提供私密环境、精致餐饮与高规格服务。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州西子湖四季酒店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州法云安缦', 'hotel', '西湖区西湖街道法云弄22号',
       30.2419, 120.1126, 5200.00, NULL, '14:00后入住', '住宿,奢华型', 4.9,
       '奢华型隐逸度假酒店，坐落于灵隐景区山谷村落，强调私密、自然与定制服务。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州法云安缦' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州柏悦酒店', 'hotel', '上城区钱江路1366号',
       30.2469, 120.2136, 2200.00, NULL, '15:00后入住', '住宿,奢华型', 4.8,
       '奢华型城市酒店，拥有高空钱塘江景观、精致餐饮与私密服务。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州柏悦酒店' AND category='hotel'
);

INSERT INTO poi_knowledge (city, name, category, address, latitude, longitude,
                           ticket_price, duration_min, open_time, tags, rating, description)
SELECT '杭州', '杭州紫萱度假村', 'hotel', '西湖区八盘岭路1号',
       30.2288, 120.1391, 3800.00, NULL, '15:00后入住', '住宿,奢华型', 4.8,
       '奢华型精品度假酒店，隐于西湖景区园林之中，客房数量少且私密性强。'
WHERE NOT EXISTS (
    SELECT 1 FROM poi_knowledge WHERE city='杭州' AND name='杭州紫萱度假村' AND category='hotel'
);

UPDATE poi_knowledge
SET tags = CONCAT_WS(',', NULLIF(tags, ''), '奢华型'),
    description = '奢华型国宾馆级园林酒店，私享西湖一线湖景与高规格接待环境。'
WHERE city='杭州' AND name='杭州西子宾馆汪庄' AND category='hotel'
  AND (tags IS NULL OR tags NOT LIKE '%奢华型%');
