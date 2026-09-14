import os, sys
sys.path.insert(0, os.path.abspath("."))
from app.agent.generators import build_suggestions
from app.agent import poi_repository

hotels = [{"name": h["name"], "category": "hotel", "id": h["id"],
           "ticket_price": float(h["ticket_price"] or 0),
           "address": h.get("address"), "latitude": h.get("latitude"),
           "longitude": h.get("longitude")} for h in poi_repository.list_hotel_pois("巴厘岛")]
plans = [{"day_no": 1, "items": [
    {"poi_name": "乌布猴林", "item_type": "attraction"},
    {"poi_name": "四季酒店萨延", "item_type": "hotel"},
]}]
raw = [
    {"name": "某景点A", "category": "attraction", "intro": "x"},
    {"name": "某景点B", "category": "attraction", "intro": "x"},
    {"name": "某美食A", "category": "food", "intro": "x"},
]
rows = build_suggestions(plans, [], [], hotels, raw, allow_external=True)
from collections import Counter
print(Counter(r["category"] for r in rows))
for r in rows:
    print(r["category"], r["name"], r.get("estimated_cost"))
