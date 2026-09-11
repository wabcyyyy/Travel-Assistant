-- 对齐价格契约：餐饮/酒店将 avg_cost 同步到 ticket_price（预算引擎优先读 ticket_price）
UPDATE poi_knowledge
SET ticket_price = avg_cost
WHERE city = '巴厘岛'
  AND category IN ('food', 'hotel')
  AND ticket_price IS NULL
  AND avg_cost IS NOT NULL;
