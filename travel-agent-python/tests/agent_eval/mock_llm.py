"""离线评测数据面：模拟权威检索结果与确定性 LLM 输出。

LLM-only 口径下生产链路不再有确定性 fallback，因此离线评测改为
mock 开放模式的模型输出（fixture_open_day / fixture_open_trip）：
从固定 fixture 目录按序取点生成合法行程 JSON，不依赖真实 LLM，
但走真实的编排/落地/反思/格式化链路。
"""

from __future__ import annotations

from copy import deepcopy

from app.agent.trace import traced


def _attractions(city: str) -> list[dict]:
    return [
        {
            "id": i,
            "name": f"{city}景点{i}",
            "category": "attraction",
            "address": f"{city}示例区{i}",
            "latitude": 30.0 + i / 100,
            "longitude": 120.0 + i / 100,
            "ticket_price": 20 + i * 5,
            "duration_min": 90,
            "open_time": "08:00-18:00",
            "tags": "人文 自然 网红",
            "rating": 4.8,
        }
        for i in range(1, 13)
    ]


def _foods(city: str) -> list[dict]:
    return [
        {
            "id": 100 + i,
            "name": f"{city}本地餐厅{i}",
            "category": "food",
            "address": f"{city}美食街{i}",
            "latitude": 30.02 + i / 100,
            "longitude": 120.02 + i / 100,
            "ticket_price": 60 + i * 10,
            "duration_min": 60,
            "open_time": "10:00-22:00",
            "tags": "美食",
        }
        for i in range(1, 5)
    ]


def _hotels(city: str) -> list[dict]:
    return [
        {
            "id": 200 + i,
            "name": f"{city}舒适酒店{i}",
            "category": "hotel",
            "address": f"{city}市中心{i}",
            "ticket_price": 300 + i * 50,
            "description": "舒适型酒店",
            "tags": "住宿",
        }
        for i in range(1, 3)
    ]


def catalog(city: str) -> dict:
    return {
        "attractions": _attractions(city),
        "foods": _foods(city),
        "hotels": _hotels(city),
        "consumption": {"city": city, "meal_price": 60, "transport_price": 35, "hotel_price": 300},
    }


@traced("tool", "fixture.search_attractions")
def search_attractions(city: str, preferences: list[str], limit: int = 30) -> list[dict]:
    return deepcopy(catalog(city)["attractions"][:limit])


@traced("tool", "fixture.search_foods")
def search_foods(city: str, limit: int = 10) -> list[dict]:
    return deepcopy(catalog(city)["foods"][:limit])


@traced("tool", "fixture.search_hotels")
def search_hotels(city: str, limit: int = 6) -> list[dict]:
    return deepcopy(catalog(city)["hotels"][:limit])


@traced("tool", "fixture.get_consumption")
def get_consumption(city: str) -> dict:
    return deepcopy(catalog(city)["consumption"])


def attach_poi_images(plan: list[dict], city: str) -> list[dict]:
    return plan


@traced("tool", "fixture.search_local_poi")
def search_local_poi(city: str, name: str, *, category: str | None = None) -> list[dict]:
    """按名称回放 fixture 坐标，供开放模式的 local_ground 离线落点。"""
    for group in (_attractions(city), _foods(city), _hotels(city)):
        for poi in group:
            if poi["name"] == name:
                return [deepcopy(poi)]
    return []


def plan_research(task) -> dict:
    """确定性研究规划：不扩展检索参数（等价阶段一的确定性行为）。"""
    return {}


def evaluate_research(task, items: list[dict], round_no: int) -> dict:
    """确定性研究评估：结果非空即视为充分（等价阶段一的确定性行为）。"""
    return {"sufficient": True, "extra_keywords": []}


def _take_unused(pool: list[dict], used: set[str], offset: int) -> dict | None:
    for poi in pool[offset:]:
        if poi["name"] not in used:
            return deepcopy(poi)
    return None


def _item(poi: dict, start: str, end: str) -> dict:
    return {
        "item_type": poi["category"],
        "poi_name": poi["name"],
        "start_time": start,
        "end_time": end,
        "duration_min": poi.get("duration_min") or 90,
        "cost": float(poi.get("ticket_price") or 0),
        "tag": poi.get("tags"),
    }


def fixture_open_day(req, used: set[str]) -> dict:
    """确定性单日开放模式输出：2 景点 + 1 餐饮 + 1 酒店（名字来自 fixture）。"""
    city = req.city
    data = catalog(city)
    offset = (req.day_no - 1) * 2
    a1 = _take_unused(data["attractions"], used, offset)
    a2 = _take_unused(data["attractions"], used, offset + 1)
    food = _take_unused(data["foods"], used, (req.day_no - 1) % len(data["foods"]))
    hotel = data["hotels"][(req.day_no - 1) % len(data["hotels"])]
    items = []
    if a1:
        items.append(_item(a1, "09:00", "10:30"))
    if a2:
        items.append(_item(a2, "11:00", "12:30"))
    if food:
        items.append(_item(food, "18:00", "19:00"))
    if req.needs_hotel:
        items.append(_item(hotel, "21:00", "08:00"))
    return {"note": f"{city}第{req.day_no}天行程", "items": items, "suggestions": []}


def fixture_open_trip(req) -> tuple[list[dict], list[dict]]:
    """确定性多日开放模式输出：逐天展开 fixture_open_day（day_no 逐天递增）。"""
    days = req.days or 1
    plans = []
    taken: set[str] = set()
    for day_no in range(1, days + 1):
        day_req = req.model_copy(update={"day_no": day_no})
        plan = fixture_open_day(day_req, taken)
        for item in plan["items"]:
            taken.add(item["poi_name"])
        plan["day_no"] = day_no
        plans.append(plan)
    return plans, []
