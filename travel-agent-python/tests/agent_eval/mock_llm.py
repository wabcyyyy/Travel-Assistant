"""离线评测数据面：模拟权威检索结果，不模拟模型输出。"""

from __future__ import annotations

from copy import deepcopy

from app.agent.trace import traced


def _attractions(city: str) -> list[dict]:
    return [
        {"id": i, "name": f"{city}景点{i}", "category": "attraction",
         "address": f"{city}示例区{i}", "latitude": 30.0 + i / 100,
         "longitude": 120.0 + i / 100, "ticket_price": 20 + i * 5,
         "duration_min": 90, "open_time": "08:00-18:00",
         "tags": "人文 自然 网红", "rating": 4.8}
        for i in range(1, 13)
    ]


def _foods(city: str) -> list[dict]:
    return [
        {"id": 100 + i, "name": f"{city}本地餐厅{i}", "category": "food",
         "address": f"{city}美食街{i}", "latitude": 30.02 + i / 100,
         "longitude": 120.02 + i / 100, "ticket_price": 60 + i * 10,
         "duration_min": 60, "open_time": "10:00-22:00", "tags": "美食"}
        for i in range(1, 5)
    ]


def _hotels(city: str) -> list[dict]:
    return [
        {"id": 200 + i, "name": f"{city}舒适酒店{i}", "category": "hotel",
         "address": f"{city}市中心{i}", "ticket_price": 300 + i * 50,
         "description": "舒适型酒店", "tags": "住宿"}
        for i in range(1, 3)
    ]


def catalog(city: str) -> dict:
    return {
        "attractions": _attractions(city),
        "foods": _foods(city),
        "hotels": _hotels(city),
        "consumption": {"city": city, "meal_price": 60, "transport_price": 35,
                        "hotel_price": 300},
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
