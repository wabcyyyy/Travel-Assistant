-- 巴厘岛种子 POI（真实坐标；source 标注为种子数据）
-- 用途：海外目的地在高德无覆盖、Nominatim 超时的环境下仍能检索到证据并落坐标。

INSERT INTO poi_knowledge
  (city, name, category, address, latitude, longitude, ticket_price, avg_cost, duration_min, open_time, tags, rating, description, source)
VALUES
  ('巴厘岛', '海神庙', 'attraction', 'Tanah Lot, Beraban, Kediri, Tabanan', -8.621200, 115.086800, 60.00, NULL, 90, '07:00-19:00', '寺庙,日落', 4.6, '巴厘岛标志性海上寺庙，建在离岸岩石上，日落景色极佳。', 'mysql.poi_knowledge'),
  ('巴厘岛', '乌布猴林', 'attraction', 'Jl. Monkey Forest, Ubud', -8.518500, 115.258800, 50.00, NULL, 90, '08:30-18:00', '自然,寺庙,猴子', 4.5, '乌布圣猴森林保护区，林中有普拉达姆神庙。', 'mysql.poi_knowledge'),
  ('巴厘岛', '乌鲁瓦图寺', 'attraction', 'Pura Luhur Uluwatu, Pecatu', -8.829100, 115.084900, 50.00, NULL, 90, '07:00-19:00', '寺庙,悬崖,日落', 4.5, '建在悬崖上的印度教寺庙，可观看传统凯查舞与印度洋日落。', 'mysql.poi_knowledge'),
  ('巴厘岛', '库塔海滩', 'attraction', 'Kuta Beach, Kuta', -8.718000, 115.168600, 0.00, NULL, 120, '全天开放', '海滩,冲浪', 4.2, '巴厘岛最热闹的海滩之一，适合冲浪初学者与日落漫步。', 'mysql.poi_knowledge'),
  ('巴厘岛', '德格拉朗梯田', 'attraction', 'Tegallalang Rice Terrace, Ubud', -8.431000, 115.279000, 30.00, NULL, 60, '08:00-18:00', '梯田,徒步', 4.4, '乌布北部经典水稻梯田景观，适合拍照与短途徒步。', 'mysql.poi_knowledge'),
  ('巴厘岛', '京打马尼火山', 'attraction', 'Mount Batur, Kintamani', -8.242200, 115.375000, 100.00, NULL, 240, '全天开放', '火山,日出,徒步', 4.6, '活火山观景点，凌晨徒步登顶看日出是经典行程。', 'mysql.poi_knowledge'),
  ('巴厘岛', '水神庙', 'attraction', 'Ulun Danu Beratan Temple, Bedugul', -8.275000, 115.166700, 50.00, NULL, 90, '08:00-18:00', '寺庙,湖景', 4.5, '布拉坦湖上的水上寺庙，巴厘岛明信片取景地。', 'mysql.poi_knowledge'),
  ('巴厘岛', '金巴兰海滩', 'attraction', 'Jimbaran Beach, Jimbaran', -8.790000, 115.160000, 0.00, NULL, 120, '全天开放', '海滩,海鲜,日落', 4.3, '以海滩海鲜烧烤与日落闻名的海湾。', 'mysql.poi_knowledge'),
  ('巴厘岛', '圣泉寺', 'attraction', 'Tirta Empul Temple, Tampaksiring', -8.415000, 115.315000, 50.00, NULL, 90, '08:00-18:00', '寺庙,泉水', 4.5, '千年历史的圣泉净化寺庙，可体验传统沐浴仪式。', 'mysql.poi_knowledge'),
  ('巴厘岛', '象窟', 'attraction', 'Goa Gajah, Bedulu', -8.518000, 115.290000, 30.00, NULL, 60, '08:00-16:00', '古迹,石雕', 4.2, '联合国教科文组织相关古迹，以洞口石雕闻名。', 'mysql.poi_knowledge'),
  ('巴厘岛', '水明漾海滩', 'attraction', 'Seminyak Beach, Seminyak', -8.690500, 115.168000, 0.00, NULL, 90, '全天开放', '海滩,日落,酒吧', 4.3, '高端度假区海滩，日落酒吧与设计酒店集中。', 'mysql.poi_knowledge'),
  ('巴厘岛', '努沙杜瓦海滩', 'attraction', 'Nusa Dua Beach, Nusa Dua', -8.800000, 115.230000, 0.00, NULL, 120, '全天开放', '海滩,度假', 4.4, '水质清澈、坡度平缓的度假区海滩，适合家庭。', 'mysql.poi_knowledge'),
  ('巴厘岛', '乌布市场', 'attraction', 'Ubud Traditional Art Market, Ubud', -8.507000, 115.262000, 0.00, NULL, 60, '08:00-18:00', '市场,购物', 4.1, '乌布皇宫对岸的传统艺术市场，可淘手工艺品。', 'mysql.poi_knowledge'),

  ('巴厘岛', '乌布皇宫', 'attraction', 'Ubud Royal Palace, Ubud', -8.507500, 115.262500, 0.00, NULL, 45, '08:00-19:00', '皇宫,文化', 4.3, '乌布王室宫殿，晚间常有传统舞表演。', 'mysql.poi_knowledge'),
  ('巴厘岛', '梦幻海滩', 'attraction', 'Dreamland Beach, Pecatu', -8.795000, 115.090000, 0.00, NULL, 90, '全天开放', '海滩,冲浪', 4.2, '乌鲁瓦图附近的白色沙滩，浪大适合冲浪。', 'mysql.poi_knowledge'),

  ('巴厘岛', '烤乳猪饭 Ibu Oka', 'food', 'Jl. Tegal Sari, Ubud', -8.506000, 115.263000, NULL, 40.00, 60, '10:00-18:00', '本地菜,烤乳猪', 4.4, '乌布名店，招牌 Babi Guling 烤乳猪饭。', 'mysql.poi_knowledge'),
  ('巴厘岛', '脏鸭餐 Bebek Bengil', 'food', 'Jl. Hanoman, Padang Tegal, Ubud', -8.510000, 115.265000, NULL, 80.00, 90, '10:00-22:00', '本地菜,脏鸭', 4.3, '乌布经典脏鸭餐餐厅，庭院用餐环境。', 'mysql.poi_knowledge'),
  ('巴厘岛', 'Locavore', 'food', 'Jl. Dewisita, Ubud', -8.510000, 115.262000, NULL, 350.00, 120, '12:00-14:30,18:00-21:30', 'fine dining', 4.7, '乌布知名现代印尼料理餐厅，建议提前预约。', 'mysql.poi_knowledge'),
  ('巴厘岛', '金巴兰海鲜烧烤', 'food', 'Jimbaran Bay Seafood Cafes', -8.788000, 115.162000, NULL, 150.00, 120, '16:00-23:00', '海鲜,日落', 4.3, '金巴兰湾沙滩海鲜排挡，边看日落边吃烤鱼。', 'mysql.poi_knowledge'),
  ('巴厘岛', 'Naughty Nuri''s', 'food', 'Jl. Raya Sanggingan, Ubud', -8.498000, 115.268000, NULL, 100.00, 90, '10:00-22:00', '猪肋排,酒吧', 4.4, '以马丁尼与烤猪肋排闻名的乌布餐馆。', 'mysql.poi_knowledge'),

  ('巴厘岛', '阿雅娜度假村', 'hotel', 'Jl. Karang Mas Sejahtera, Jimbaran', -8.780000, 115.150000, NULL, 2500.00, NULL, '入住15:00后', '豪华,无边泳池', 4.7, '金巴兰悬崖上的综合度假村，Rock Bar 日落著名。', 'mysql.poi_knowledge'),
  ('巴厘岛', '四季酒店萨延', 'hotel', 'Sayan, Ubud', -8.500000, 115.260000, NULL, 4000.00, NULL, '入住15:00后', '奢华,河谷', 4.8, '乌布河谷中的奢华度假村，丛林景观。', 'mysql.poi_knowledge'),
  ('巴厘岛', '穆利亚度假村', 'hotel', 'Kawasan Pariwisata ITDC NW, Nusa Dua', -8.790000, 115.220000, NULL, 2200.00, NULL, '入住15:00后', '豪华,海滩', 4.6, '努沙杜瓦大型奢华度假村，海滩与泳池设施齐全。', 'mysql.poi_knowledge'),
  ('巴厘岛', '空中花园酒店', 'hotel', 'Desa Payangan, Ubud', -8.400000, 115.280000, NULL, 3500.00, NULL, '入住15:00后', '奢华,丛林泳池', 4.7, '以层叠无边泳池与丛林景观闻名的精品酒店。', 'mysql.poi_knowledge'),
  ('巴厘岛', '帕德玛雷吉安酒店', 'hotel', 'Jl. Padma, Legian', -8.700000, 115.170000, NULL, 1200.00, NULL, '入住14:00后', '舒适,泳池', 4.4, '雷吉安海滩附近的舒适度假酒店，适合家庭。', 'mysql.poi_knowledge')
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
