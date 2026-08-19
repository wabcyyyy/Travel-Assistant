import json
import logging
from math import ceil

from app.agent import tools
from app.agent.geo import nearest_neighbor_order
from app.common.config import settings
from app.common.llm_client import get_llm_client

logger = logging.getLogger(__name__)

ATTRACTIONS_PER_DAY = 3
TIME_SLOTS = [
    ("09:00", "11:30"),
    ("13:30", "16:00"),
    ("19:00", "20:30"),
]


def fallback_generate(city: str, days: int, persons: int, preferences: list[str]) -> tuple[list[dict], dict]:
    attractions = tools.search_attractions(city, preferences)
    foods = tools.search_foods(city)
    consumption = tools.get_consumption(city)

    daily_plans: list[dict] = []
    cursor = 0
    ordered = nearest_neighbor_order(attractions)
    if not ordered:
        ordered = attractions
    for day_no in range(1, days + 1):
        items: list[dict] = []
        for slot_index in range(ATTRACTIONS_PER_DAY):
            poi = ordered[cursor % len(ordered)] if ordered else None
            cursor += 1
            if poi is None:
                continue
            start, end = TIME_SLOTS[slot_index]
            items.append(_to_item(poi, start, end))
        if foods:
            food = foods[day_no % len(foods)]
            items.append(_to_item(food, "18:00", "19:00"))
        hotel = _hotel_item(city, consumption)
        items.append(hotel)
        daily_plans.append({"day_no": day_no, "note": f"{city}第{day_no}天行程", "items": items})

    budget = _estimate_budget(attractions, foods, consumption, days, persons)
    return daily_plans, budget


def llm_generate(city: str, days: int, persons: int, preferences: list[str],
                 candidates: list[dict], foods: list[dict], consumption: dict | None) -> tuple[list[dict], dict]:
    client = get_llm_client()
    system_prompt = (
        "你是资深旅行规划师。只输出 JSON，不要输出任何其他文字，不要用 markdown 代码块。"
        "景点必须从候选列表中选择，不得编造。每天安排 3 个景点、1 家餐饮、1 家酒店。"
        "输出结构："
        '{"daily_plans":[{"day_no":1,"note":"当日备注","items":[{"item_type":"attraction",'
        '"poi_name":"名称","start_time":"09:00","end_time":"11:30","duration_min":150,'
        '"cost":60.0,"tag":"标签","remark":null}]}],'
        '"budget_estimate":{"门票":0,"餐饮":0,"交通":0,"酒店":0}}'
    )
    user_prompt = (
        f"目的地：{city}，共 {days} 天，{persons} 人出行，偏好：{'、'.join(preferences) or '无'}\n"
        f"候选景点：{json.dumps(candidates, ensure_ascii=False)}\n"
        f"候选餐饮：{json.dumps(foods, ensure_ascii=False)}\n"
        f"城市消费系数：{json.dumps(consumption, ensure_ascii=False)}\n"
        "预算按人数估算：门票=景点票价×人数，餐饮=人均每餐×2×天数×人数，"
        "交通=人均日交通×天数×人数，酒店=单间价×ceil(人数/2)×天数。"
    )
    raw = client.complete(user_prompt, system_prompt=system_prompt, temperature=0.3)
    data = _parse_json(raw)
    daily_plans = _validate_plans(data.get("daily_plans"), days)
    budget = data.get("budget_estimate")
    if not isinstance(budget, dict):
        budget = {}
    return daily_plans, budget


def _validate_plans(plans: list | None, days: int) -> list[dict]:
    if not isinstance(plans, list) or not plans:
        raise ValueError("LLM 返回的行程结构无效")
    valid: list[dict] = []
    for plan in plans:
        items = plan.get("items")
        if not isinstance(items, list) or not items:
            continue
        day_no = int(plan.get("day_no", len(valid) + 1))
        valid.append(
            {
                "day_no": day_no,
                "note": plan.get("note"),
                "items": [i for i in items if isinstance(i, dict) and i.get("poi_name")],
            }
        )
    if len(valid) < days:
        raise ValueError("LLM 返回的天数不足")
    return valid[:days]


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM 输出中未找到 JSON")
    return json.loads(text[start : end + 1])


def _to_item(poi: dict, start: str, end: str) -> dict:
    return {
        "item_type": poi.get("category", "attraction"),
        "poi_name": poi.get("name", ""),
        "poi_id": str(poi.get("id") or ""),
        "address": poi.get("address"),
        "latitude": poi.get("latitude"),
        "longitude": poi.get("longitude"),
        "start_time": start,
        "end_time": end,
        "duration_min": poi.get("duration_min"),
        "cost": poi.get("ticket_price"),
        "tag": poi.get("tags"),
        "remark": None,
    }


def _hotel_item(city: str, consumption: dict | None) -> dict:
    price = consumption.get("hotel_price", 300.0) if consumption else 300.0
    return {
        "item_type": "hotel",
        "poi_name": f"{city}市区舒适酒店",
        "poi_id": None,
        "address": f"{city}市中心商圈",
        "latitude": None,
        "longitude": None,
        "start_time": "21:00",
        "end_time": "08:00",
        "duration_min": 660,
        "cost": round(float(price), 2),
        "tag": "酒店",
        "remark": "按单间计费",
    }


def _estimate_budget(attractions: list[dict], foods: list[dict], consumption: dict | None,
                     days: int, persons: int) -> dict:
    ticket = sum(float(a.get("ticket_price") or 0) for a in attractions) / max(len(attractions), 1) * 3
    meal = float(consumption.get("meal_price", 60.0) if consumption else 60.0) * 2
    transport = float(consumption.get("transport_price", 35.0) if consumption else 35.0)
    hotel = float(consumption.get("hotel_price", 300.0) if consumption else 300.0)
    rooms = ceil(persons / 2)
    return {
        "门票": round(ticket * persons, 2),
        "餐饮": round(meal * days * persons, 2),
        "交通": round(transport * days * persons, 2),
        "酒店": round(hotel * rooms * days, 2),
    }