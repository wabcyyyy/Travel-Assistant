import sys
sys.path.insert(0, "travel-agent-python")
from app.agent import poi_repository, tools
from app.agent.workflow import _floor_suggestions

hotels = poi_repository.list_hotel_pois("巴厘岛")
print("hotels", [(h.get("name"), h.get("category"), h.get("ticket_price")) for h in hotels])
sh = tools.search_hotels("巴厘岛", limit=10)
print("search_hotels", len(sh), [h.get("name") for h in sh])
f = _floor_suggestions(
    [{"name": "某景点", "category": "attraction"}],
    [{"name": h.get("name"), "category": "hotel", "ticket_price": h.get("ticket_price"), "avg_cost": h.get("avg_cost"), "id": h.get("id"), "description": h.get("description"), "latitude": h.get("latitude"), "longitude": h.get("longitude"), "source": h.get("source")} for h in hotels]
    + [{"name": "某美食", "category": "food", "id": 1}],
)
from collections import Counter
print("floor", Counter(x.get("category") for x in f))
for x in f:
    if x.get("category") == "hotel":
        print(" hotel", x.get("name"), x.get("estimated_cost"))
