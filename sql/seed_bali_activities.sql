-- 巴厘岛体验类种子（category=activity），供「发现更多-体验」地板与引用式生成
INSERT INTO poi_knowledge
  (city, name, category, address, latitude, longitude, ticket_price, avg_cost, duration_min, open_time, tags, rating, description, source)
VALUES
  ('巴厘岛', '图兰奔潜水', 'activity', 'Tulamben, Karangasem', -8.278000, 115.595000, NULL, 600.00, 240, '08:00-16:00', '潜水,体验', 4.7, '图兰奔沉船潜水点，适合浮潜与体验潜水。', 'mysql.poi_knowledge'),
  ('巴厘岛', '乌布丛林秋千', 'activity', 'Bali Swing, Ubud', -8.425000, 115.285000, NULL, 200.00, 120, '08:00-17:00', '体验,网红出片', 4.5, '丛林高空秋千与鸟巢拍照点，需预约。', 'mysql.poi_knowledge'),
  ('巴厘岛', '巴厘岛传统舞表演', 'activity', 'Ubud Palace / ARMA Museum', -8.507500, 115.262500, NULL, 80.00, 90, '19:00-21:00', '演出,文化', 4.4, '传统巴龙舞/凯查舞晚间演出。', 'mysql.poi_knowledge'),
  ('巴厘岛', '金巴兰SPA体验', 'activity', 'Jimbaran Spa Area', -8.780000, 115.160000, NULL, 350.00, 120, '10:00-21:00', 'SPA,体验', 4.5, '悬崖海景 SPA，建议提前预约。', 'mysql.poi_knowledge'),
  ('巴厘岛', '库塔冲浪课', 'activity', 'Kuta Beach Surf School', -8.718000, 115.168600, NULL, 250.00, 120, '07:00-17:00', '冲浪,体验', 4.3, '适合初学者的海滩冲浪体验课。', 'mysql.poi_knowledge'),
  ('巴厘岛', '阿勇河漂流', 'activity', 'Ayung River Rafting, Ubud', -8.500000, 115.240000, NULL, 280.00, 180, '09:00-15:00', '漂流,体验', 4.6, '乌布阿勇河漂流，含酒店接送套餐常见。', 'mysql.poi_knowledge')
ON DUPLICATE KEY UPDATE
  latitude = VALUES(latitude),
  longitude = VALUES(longitude),
  ticket_price = VALUES(ticket_price),
  avg_cost = VALUES(avg_cost),
  open_time = VALUES(open_time),
  rating = VALUES(rating),
  description = VALUES(description),
  source = VALUES(source),
  source_updated_at = NOW();
